"""Shared path-matching utility used by resolver and checker."""

from __future__ import annotations

import fnmatch
from pathlib import Path


def path_matches_pattern(pattern: str, path: Path) -> bool:
    """Return True if path matches a glob pattern.

    Tries matching against:
    1. Full absolute path string (for absolute patterns).
    2. All trailing subpaths of increasing depth — e.g. for /a/b/c/d.py:
       a/b/c/d.py, b/c/d.py, c/d.py, d.py  (handles "agentmd/**/*.py").
    3. Filename alone (for simple "*.py" patterns).
    """
    if fnmatch.fnmatch(str(path), pattern):
        return True
    if fnmatch.fnmatch(path.name, pattern):
        return True
    parts = path.parts
    for i in range(len(parts)):
        sub = "/".join(parts[i:])
        if fnmatch.fnmatch(sub, pattern):
            return True
    return False


def rule_applies_to_path(
    applies_to: list[str],
    exceptions: list[str],
    target: Path,
) -> bool:
    """Return True if the given applies_to/exceptions lists match target."""
    if not any(path_matches_pattern(p, target) for p in applies_to):
        return False
    if any(path_matches_pattern(p, target) for p in exceptions):
        return False
    return True
