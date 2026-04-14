"""Rule violation checker — pattern matching against file contents."""

from __future__ import annotations

import re
from pathlib import Path

from agentmd.models import RuleFile
from agentmd.resolver import ResolvedContext

# Map of well-known rule IDs to pattern-based checks.
# Each entry: (pattern_regex, violation_message_template)
# Conservative: only check rules whose ID matches known patterns.
_KNOWN_CHECKS: dict[str, tuple[re.Pattern[str], str]] = {
    "no-raw-sql": (
        re.compile(r'(execute|cursor\.execute)\s*\(\s*["\']', re.IGNORECASE),
        "Raw SQL string passed to execute(). Use the ORM layer instead.",
    ),
    "no-print-statements": (
        re.compile(r"^\s*print\s*\(", re.MULTILINE),
        "print() call found. Use the project logger instead.",
    ),
    "type-hints-required": (
        re.compile(r"^def \w+\([^)]*\)\s*:", re.MULTILINE),
        "Function definition without return type annotation found.",
    ),
    "no-console-log": (
        re.compile(r"\bconsole\.log\s*\(", re.MULTILINE),
        "console.log() found. Remove debug logging before commit.",
    ),
    "no-todo-comments": (
        re.compile(r"#\s*TODO", re.IGNORECASE),
        "TODO comment found. Resolve or create a ticket.",
    ),
}


def check_file(target: Path, ctx: ResolvedContext) -> dict[str, str]:
    """Check target file against active rules.

    Returns dict of {rule_id: violation_message} for rules that are violated.
    Rules without a known pattern checker are silently skipped (conservative).
    """
    if not target.is_file():
        return {}

    try:
        content = target.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}

    violations: dict[str, str] = {}

    for rule in ctx.active_rules:
        checker = _KNOWN_CHECKS.get(rule.id)
        if checker is None:
            # No pattern check defined for this rule — skip
            continue
        pattern, message = checker
        if pattern.search(content):
            violations[rule.id] = message

    return violations
