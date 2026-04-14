"""Rule violation checker — AST-based and pattern-based analysis.

check_file()   — check a single file, return violations with line numbers
scan_repo()    — scan all matching files in a repo, return aggregated results
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from agentmd.models import RuleFile
from agentmd.resolver import ResolvedContext
from agentmd.utils import rule_applies_to_path


# ---------------------------------------------------------------------------
# Violation detail
# ---------------------------------------------------------------------------


@dataclass
class ViolationDetail:
    """A single violation found in a file."""

    message: str
    line: int | None = None  # 1-based line number, or None if not determinable


@dataclass
class FileViolations:
    """All violations found in one file."""

    path: Path
    violations: dict[str, list[ViolationDetail]] = field(default_factory=dict)

    @property
    def has_errors(self) -> bool:
        return bool(self.violations)


# ---------------------------------------------------------------------------
# AST-based checkers (Python files only)
# ---------------------------------------------------------------------------


def _ast_check_no_print_statements(content: str) -> list[ViolationDetail]:
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return []

    results: list[ViolationDetail] = []
    for node in ast.walk(tree):
        # Match: print(...)  as a standalone expression statement
        if (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "print"
        ):
            results.append(
                ViolationDetail(
                    message="print() call found. Use the project logger instead.",
                    line=node.lineno,
                )
            )
    return results


def _ast_check_no_raw_sql(content: str) -> list[ViolationDetail]:
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return []

    _SQL_KEYWORDS = {"SELECT", "INSERT", "UPDATE", "DELETE", "CREATE", "DROP", "ALTER"}
    results: list[ViolationDetail] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        # .execute("SELECT ...") or cursor.execute("...")
        if not (isinstance(node.func, ast.Attribute) and node.func.attr in ("execute", "executemany")):
            continue
        if not node.args:
            continue
        first_arg = node.args[0]
        # Allow only if the first arg is NOT a string literal
        if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
            sql = first_arg.value.upper().strip()
            if any(kw in sql for kw in _SQL_KEYWORDS):
                results.append(
                    ViolationDetail(
                        message=(
                            f"Raw SQL string passed to {node.func.attr}(). "
                            "Use the ORM layer instead."
                        ),
                        line=node.lineno,
                    )
                )
    return results


def _ast_check_type_hints_required(content: str) -> list[ViolationDetail]:
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return []

    results: list[ViolationDetail] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        name = node.name
        # Skip private/dunder methods
        if name.startswith("_"):
            continue

        # Missing return annotation
        if node.returns is None:
            results.append(
                ViolationDetail(
                    message=f"Function '{name}' missing return type annotation.",
                    line=node.lineno,
                )
            )

        # Missing parameter annotations
        for arg in node.args.args + node.args.posonlyargs + node.args.kwonlyargs:
            if arg.arg in ("self", "cls"):
                continue
            if arg.annotation is None:
                results.append(
                    ViolationDetail(
                        message=(
                            f"Parameter '{arg.arg}' in function '{name}' "
                            "missing type annotation."
                        ),
                        line=node.lineno,
                    )
                )
    return results


# ---------------------------------------------------------------------------
# Regex-based checkers (language-agnostic fallback)
# ---------------------------------------------------------------------------


def _regex_check(pattern: re.Pattern[str], message: str, content: str) -> list[ViolationDetail]:
    results: list[ViolationDetail] = []
    lines = content.splitlines()
    for i, line in enumerate(lines, start=1):
        if pattern.search(line):
            results.append(ViolationDetail(message=message, line=i))
    return results


def _regex_no_console_log(content: str) -> list[ViolationDetail]:
    return _regex_check(
        re.compile(r"\bconsole\.log\s*\("),
        "console.log() found. Remove debug logging before commit.",
        content,
    )


def _regex_no_todo_comments(content: str) -> list[ViolationDetail]:
    return _regex_check(
        re.compile(r"#\s*TODO|//\s*TODO|/\*\s*TODO", re.IGNORECASE),
        "TODO comment found. Resolve or create a ticket.",
        content,
    )


# ---------------------------------------------------------------------------
# Rule ID → checker dispatch
# ---------------------------------------------------------------------------

# For Python files: prefer AST-based checks
_PYTHON_CHECKS: dict[str, Callable[[str], list[ViolationDetail]]] = {
    "no-print-statements": _ast_check_no_print_statements,
    "no-raw-sql": _ast_check_no_raw_sql,
    "type-hints-required": _ast_check_type_hints_required,
}

# Language-agnostic regex checks (run on any file)
_GENERIC_CHECKS: dict[str, Callable[[str], list[ViolationDetail]]] = {
    "no-console-log": _regex_no_console_log,
    "no-todo-comments": _regex_no_todo_comments,
    # Regex fallbacks for rules that also have AST versions
    "no-print-statements": lambda c: _regex_check(
        re.compile(r"^\s*print\s*\(", re.MULTILINE),
        "print() call found. Use the project logger instead.",
        c,
    ),
    "no-raw-sql": lambda c: _regex_check(
        re.compile(r"(execute|cursor\.execute)\s*\(\s*[\"']", re.IGNORECASE),
        "Raw SQL string passed to execute(). Use the ORM layer instead.",
        c,
    ),
}


def _get_checker(
    rule_id: str, path: Path
) -> Callable[[str], list[ViolationDetail]] | None:
    """Return the best available checker for rule_id on the given file."""
    if path.suffix == ".py" and rule_id in _PYTHON_CHECKS:
        return _PYTHON_CHECKS[rule_id]
    return _GENERIC_CHECKS.get(rule_id)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def check_file(
    target: Path, ctx: ResolvedContext
) -> dict[str, list[ViolationDetail]]:
    """Check target against its active rules.

    Returns dict of {rule_id: [ViolationDetail, ...]} for violated rules.
    Rules without a known checker are silently skipped.
    """
    if not target.is_file():
        return {}

    try:
        content = target.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}

    violations: dict[str, list[ViolationDetail]] = {}
    for rule in ctx.active_rules:
        checker = _get_checker(rule.id, target)
        if checker is None:
            continue
        found = checker(content)
        if found:
            violations[rule.id] = found
    return violations


def scan_repo(root: Path) -> dict[Path, FileViolations]:
    """Check all files in root against every applicable rule.

    Discovers rules by scanning all *.rule.md files under root, then walks
    the directory tree to find files that match each rule's applies_to patterns.

    Returns dict of {path: FileViolations} for files with at least one violation.
    """
    from agentmd.parser import find_all_agentmd_files, parse_file
    from agentmd.models import RuleFile

    # Collect all rules
    rules: list[RuleFile] = []
    for fpath in find_all_agentmd_files(root):
        try:
            parsed = parse_file(fpath)
            if isinstance(parsed, RuleFile):
                rules.append(parsed)
        except Exception:
            pass

    if not rules:
        return {}

    results: dict[Path, FileViolations] = {}

    for fpath in sorted(root.rglob("*")):
        if not fpath.is_file():
            continue
        # Skip .git and hidden directories
        if any(part.startswith(".") for part in fpath.relative_to(root).parts):
            continue
        # Skip binary files by extension heuristic
        if fpath.suffix in {
            ".pyc", ".pyo", ".so", ".dll", ".exe", ".bin",
            ".png", ".jpg", ".gif", ".ico", ".woff", ".woff2", ".ttf",
            ".zip", ".tar", ".gz", ".lock",
        }:
            continue

        applicable = [
            r for r in rules
            if rule_applies_to_path(r.applies_to, r.exceptions, fpath)
        ]
        if not applicable:
            continue

        try:
            content = fpath.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        fv = FileViolations(path=fpath)
        for rule in applicable:
            checker = _get_checker(rule.id, fpath)
            if checker is None:
                continue
            found = checker(content)
            if found:
                fv.violations[rule.id] = found

        if fv.has_errors:
            results[fpath] = fv

    return results
