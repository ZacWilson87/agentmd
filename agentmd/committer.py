"""Commit-gate: semantic diffing, rule enforcement, and scope detection.

The Committer is the bridge between the Resolver and a VCS commit workflow.
It:

1. Collects the staged files via ``git diff --cached --name-only``.
2. Resolves agentmd context for each staged file.
3. Runs rule checks (including linter_command / linter_regex) on every file.
4. Detects *critical*-severity violations that must block the commit.
5. Infers a conventional-commit ``type(scope)`` from the resolved context.

Public API
----------
get_staged_files(root)   → list[Path]
analyze_staged(root)     → CommitAnalysis
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class CommitViolation:
    """A single rule violation found in a staged file."""

    file: Path
    rule_id: str
    severity: str  # "critical" | "error" | "warning" | "info"
    message: str
    line: int | None = None


@dataclass
class CommitAnalysis:
    """The result of analysing staged files before a commit."""

    staged_files: list[Path]
    violations: list[CommitViolation]
    suggested_scope: str | None
    suggested_type: str  # conventional commit type
    contexts: dict[str, Any] = field(default_factory=dict)  # str(file) → ResolvedContext

    # ---------- derived helpers ----------

    @property
    def critical_violations(self) -> list[CommitViolation]:
        return [v for v in self.violations if v.severity == "critical"]

    @property
    def error_violations(self) -> list[CommitViolation]:
        return [v for v in self.violations if v.severity in ("critical", "error")]

    @property
    def is_blocked(self) -> bool:
        """True when at least one *critical* rule is violated."""
        return bool(self.critical_violations)

    def format_message(self, description: str = "") -> str:
        """Return a conventional-commit message template.

        Example:  ``feat(db): <description>``
        """
        scope = f"({self.suggested_scope})" if self.suggested_scope else ""
        body = description or "<description>"
        return f"{self.suggested_type}{scope}: {body}"


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------


def get_staged_files(root: Path) -> list[Path]:
    """Return the list of staged (cached) file paths relative to *root*.

    Returns an empty list if git is not available or no files are staged.
    """
    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
            capture_output=True,
            text=True,
            cwd=str(root),
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []

    if result.returncode != 0:
        return []

    files: list[Path] = []
    for line in result.stdout.strip().splitlines():
        line = line.strip()
        if line:
            candidate = (root / line).resolve()
            if candidate.is_file():
                files.append(candidate)
    return files


def _git_status_map(root: Path) -> dict[str, str]:
    """Return a mapping of file → git status letter for staged files.

    Status letters: A (added), M (modified), D (deleted), R (renamed), …
    """
    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-status", "--diff-filter=ACMR"],
            capture_output=True,
            text=True,
            cwd=str(root),
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return {}

    mapping: dict[str, str] = {}
    for line in result.stdout.strip().splitlines():
        parts = line.strip().split("\t", 1)
        if len(parts) == 2:
            status, fname = parts
            mapping[fname.strip()] = status[0]  # first char: A/M/C/R…
    return mapping


# ---------------------------------------------------------------------------
# Scope + type inference
# ---------------------------------------------------------------------------


def _suggest_scope(
    staged_files: list[Path],
    contexts: dict[str, Any],
    root: Path,
) -> str | None:
    """Infer the conventional-commit scope from files + agentmd context.

    Priority:
    1. Most-frequent skill *tag* across all resolved contexts.
    2. Package/module AGENTS.md scope — use its directory name.
    3. Longest common subdirectory of all staged files.
    Returns ``None`` when no signal is found (files span unrelated areas).
    """
    from agentmd.resolver import ResolvedContext

    tag_freq: dict[str, int] = {}
    dir_scope: dict[str, int] = {}

    for file_str, ctx in contexts.items():
        if not isinstance(ctx, ResolvedContext):
            continue
        # Skill tags (most specific signal)
        for skill in ctx.active_skills:
            for tag in skill.tags:
                tag_freq[tag] = tag_freq.get(tag, 0) + 1
        # Package/module AGENTS.md
        if ctx.agents_file and ctx.agents_file.scope in ("package", "module"):
            scope_dir = Path(file_str).parent.name
            dir_scope[scope_dir] = dir_scope.get(scope_dir, 0) + 1

    if tag_freq:
        return max(tag_freq, key=lambda t: tag_freq[t])

    if dir_scope:
        return max(dir_scope, key=lambda d: dir_scope[d])

    # Common subdirectory fallback
    if len(staged_files) >= 1:
        try:
            parts_list = [f.relative_to(root).parts for f in staged_files]
            if parts_list and len(parts_list[0]) > 1:
                common = list(parts_list[0])
                for parts in parts_list[1:]:
                    common = [a for a, b in zip(common, parts) if a == b]
                if len(common) >= 1 and common[0] not in (".", ""):
                    return common[0]  # top-level subdirectory
        except ValueError:
            pass

    return None


def _suggest_type(staged_files: list[Path], status_map: dict[str, str]) -> str:
    """Infer the conventional-commit type from staged file patterns.

    ``feat``   — default; new/modified source files
    ``fix``    — all staged files are modifications (no new files)
    ``docs``   — all staged files are Markdown or in docs/
    ``test``   — all staged files are in tests/ or match test_*.py / *.test.*
    ``chore``  — only config or meta files (pyproject, .gitignore, etc.)
    """
    if not staged_files:
        return "chore"

    paths_lower = [str(f).lower() for f in staged_files]
    basenames = [f.name.lower() for f in staged_files]

    def all_match(pred: Any) -> bool:
        return all(pred(p) for p in paths_lower)

    # Only Markdown / docs
    if all_match(lambda p: p.endswith(".md") or "/docs/" in p):
        return "docs"

    # Only test files
    if all_match(
        lambda p: "/tests/" in p or "/test/" in p
        or any(b.startswith("test_") or ".test." in b for b in basenames)
    ):
        return "test"

    # Only config / meta files
    _CONFIG_NAMES = {
        "pyproject.toml", "setup.cfg", "setup.py", ".gitignore",
        ".pre-commit-config.yaml", "makefile", "dockerfile", ".env",
        "requirements.txt", "poetry.lock", "uv.lock",
    }
    if all(b in _CONFIG_NAMES for b in basenames):
        return "chore"

    # If ALL staged files are modifications (no new files), lean toward "fix"
    if status_map and all(status_map.get(str(f.name), "M") == "M" for f in staged_files):
        return "fix"

    return "feat"


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------


def analyze_staged(root: Path) -> CommitAnalysis:
    """Analyse staged files and return a :class:`CommitAnalysis`.

    Steps:
    1. Get staged files via ``git diff --cached``.
    2. Resolve agentmd context for each file.
    3. Run ``check_file()`` (built-in + linter_command + linter_regex).
    4. Collect violations, classify by severity.
    5. Infer ``suggested_scope`` and ``suggested_type``.
    """
    from agentmd.checker import check_file
    from agentmd.resolver import resolve

    staged = get_staged_files(root)
    status_map = _git_status_map(root)

    contexts: dict[str, Any] = {}
    all_violations: list[CommitViolation] = []

    for fpath in staged:
        ctx = resolve(fpath)
        contexts[str(fpath)] = ctx

        if not ctx.active_rules:
            continue

        rule_map = {r.id: r for r in ctx.active_rules}
        file_violations = check_file(fpath, ctx)

        for rule_id, details in file_violations.items():
            rule = rule_map.get(rule_id)
            severity = rule.severity if rule else "error"
            for detail in details:
                all_violations.append(
                    CommitViolation(
                        file=fpath,
                        rule_id=rule_id,
                        severity=severity,
                        message=detail.message,
                        line=detail.line,
                    )
                )

    scope = _suggest_scope(staged, contexts, root)
    commit_type = _suggest_type(staged, status_map)

    return CommitAnalysis(
        staged_files=staged,
        violations=all_violations,
        suggested_scope=scope,
        suggested_type=commit_type,
        contexts=contexts,
    )
