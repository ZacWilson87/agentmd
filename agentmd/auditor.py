"""Comprehensive audit: validate + check + drift + trust in one pass."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agentmd.checker import FileViolations, scan_repo
from agentmd.discovery import DriftIssue, check_drift
from agentmd.models import AgentsFile
from agentmd.parser import ParseError, find_all_agentmd_files, parse_file
from agentmd.trust import TrustResult, verify_all_skills


# ---------------------------------------------------------------------------
# Report dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ValidationResult:
    path: Path
    valid: bool
    error: str | None = None


@dataclass
class AuditReport:
    """Full audit report for a repository."""

    root: Path

    # Schema validation results
    validation: list[ValidationResult] = field(default_factory=list)

    # Rule violation results per file
    violations: dict[Path, FileViolations] = field(default_factory=dict)

    # Context drift issues (AGENTS.md vs project reality)
    drift: list[DriftIssue] = field(default_factory=list)

    # SKILL.md trust verification results
    trust: list[TrustResult] = field(default_factory=list)

    # ---------- summary helpers ----------

    @property
    def validation_errors(self) -> list[ValidationResult]:
        return [r for r in self.validation if not r.valid]

    @property
    def total_violations(self) -> int:
        return sum(len(fv.violations) for fv in self.violations.values())

    @property
    def error_violations(self) -> int:
        """Count rule violations from *error*- or *critical*-severity rules."""
        from agentmd.models import RuleFile

        # Gather all rule severities
        rule_severities: dict[str, str] = {}
        for fpath in find_all_agentmd_files(self.root):
            try:
                parsed = parse_file(fpath)
                if isinstance(parsed, RuleFile):
                    rule_severities[parsed.id] = parsed.severity
            except Exception:
                pass

        count = 0
        for fv in self.violations.values():
            for rule_id in fv.violations:
                if rule_severities.get(rule_id) in ("error", "critical"):
                    count += len(fv.violations[rule_id])
        return count

    @property
    def untrusted_skills(self) -> list[TrustResult]:
        return [r for r in self.trust if r.status != "trusted"]

    @property
    def passed(self) -> bool:
        return (
            len(self.validation_errors) == 0
            and self.error_violations == 0
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "passed": self.passed,
            "summary": {
                "validation_errors": len(self.validation_errors),
                "total_violations": self.total_violations,
                "error_violations": self.error_violations,
                "drift_issues": len(self.drift),
                "untrusted_skills": len(self.untrusted_skills),
            },
            "validation": [
                {
                    "path": str(r.path),
                    "valid": r.valid,
                    "error": r.error,
                }
                for r in self.validation
            ],
            "violations": {
                str(fpath): {
                    rule_id: [
                        {"message": v.message, "line": v.line}
                        for v in vs
                    ]
                    for rule_id, vs in fv.violations.items()
                }
                for fpath, fv in self.violations.items()
            },
            "drift": [
                {
                    "kind": d.kind,
                    "message": d.message,
                    "suggestion": d.suggestion,
                }
                for d in self.drift
            ],
            "trust": [
                {
                    "path": str(r.path),
                    "status": r.status,
                    "trusted_at": r.trusted_at,
                }
                for r in self.trust
            ],
        }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_audit(root: Path) -> AuditReport:
    """Run a comprehensive audit on the repository at root.

    Steps:
    1. Validate all agentmd files (schema check).
    2. Scan all repo files against applicable rules (AST + pattern check).
    3. Check context drift (AGENTS.md vs discovered project reality).
    4. Verify SKILL.md trust state (checksum comparison).
    """
    report = AuditReport(root=root)

    # 1 — Schema validation
    for fpath in find_all_agentmd_files(root):
        try:
            parse_file(fpath)
            report.validation.append(ValidationResult(path=fpath, valid=True))
        except ParseError as exc:
            report.validation.append(
                ValidationResult(path=fpath, valid=False, error=str(exc))
            )

    # 2 — Rule violation scan across all repo files
    report.violations = scan_repo(root)

    # 3 — Drift detection: find nearest AGENTS.md to root and compare
    agents_path = root / "AGENTS.md"
    if agents_path.exists():
        try:
            parsed = parse_file(agents_path)
            if isinstance(parsed, AgentsFile):
                report.drift = check_drift(parsed, root)
        except ParseError:
            pass

    # 4 — Trust verification for all SKILL.md files
    report.trust = verify_all_skills(root)

    return report
