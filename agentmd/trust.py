"""Security & trust layer: SHA-256 checksums for SKILL.md files.

Prevents prompt injection via PRs by warning when a SKILL.md has changed
since the last trusted validation.

Trust store: .agentmd-trust.json at the repo root (can be git-tracked so
the whole team shares trusted state, or gitignored for individual control).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

TRUST_FILENAME = ".agentmd-trust.json"
_STORE_VERSION = 1

TrustStatus = Literal["trusted", "changed", "new", "missing"]


@dataclass
class TrustResult:
    """Result of verifying a single file against the trust store."""

    path: Path
    status: TrustStatus
    current_hash: str
    stored_hash: str | None
    trusted_at: str | None  # ISO 8601 timestamp or None


# ---------------------------------------------------------------------------
# Low-level store helpers
# ---------------------------------------------------------------------------


def _find_repo_root(start: Path) -> Path:
    """Walk up to find the nearest directory containing .agentmd-trust.json
    or the git root. Falls back to start if nothing is found."""
    current = start if start.is_dir() else start.parent
    while True:
        if (current / TRUST_FILENAME).exists():
            return current
        if (current / ".git").exists():
            return current
        parent = current.parent
        if parent == current:
            return start if start.is_dir() else start.parent
        current = parent


def _load_store(root: Path) -> dict:
    trust_file = root / TRUST_FILENAME
    if not trust_file.exists():
        return {"version": _STORE_VERSION, "entries": {}}
    try:
        data = json.loads(trust_file.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"version": _STORE_VERSION, "entries": {}}
        data.setdefault("version", _STORE_VERSION)
        data.setdefault("entries", {})
        return data
    except (json.JSONDecodeError, OSError):
        return {"version": _STORE_VERSION, "entries": {}}


def _save_store(root: Path, store: dict) -> None:
    trust_file = root / TRUST_FILENAME
    trust_file.write_text(
        json.dumps(store, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def compute_hash(path: Path) -> str:
    """Return the SHA-256 hex digest of a file's contents."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def verify(path: Path, root: Path | None = None) -> TrustResult:
    """Check whether path matches its stored trust hash.

    Returns a TrustResult whose status is:
    - 'trusted'  — file matches stored hash
    - 'changed'  — file hash differs from stored hash (possible tampering)
    - 'new'      — file not in trust store
    - 'missing'  — file does not exist on disk
    """
    if not path.exists():
        return TrustResult(
            path=path,
            status="missing",
            current_hash="",
            stored_hash=None,
            trusted_at=None,
        )

    if root is None:
        root = _find_repo_root(path)

    current_hash = compute_hash(path)
    store = _load_store(root)
    entries: dict[str, dict] = store["entries"]

    try:
        rel = str(path.relative_to(root))
    except ValueError:
        rel = str(path)

    if rel not in entries:
        return TrustResult(
            path=path,
            status="new",
            current_hash=current_hash,
            stored_hash=None,
            trusted_at=None,
        )

    entry = entries[rel]
    stored_hash = entry.get("hash", "")
    trusted_at = entry.get("trusted_at")
    status: TrustStatus = "trusted" if current_hash == stored_hash else "changed"

    return TrustResult(
        path=path,
        status=status,
        current_hash=current_hash,
        stored_hash=stored_hash,
        trusted_at=trusted_at,
    )


def trust_file(path: Path, root: Path | None = None) -> TrustResult:
    """Mark path as trusted by recording its current hash.

    Returns the resulting TrustResult (status will be 'trusted').
    """
    if not path.exists():
        raise FileNotFoundError(f"Cannot trust non-existent file: {path}")

    if root is None:
        root = _find_repo_root(path)

    current_hash = compute_hash(path)
    store = _load_store(root)

    try:
        rel = str(path.relative_to(root))
    except ValueError:
        rel = str(path)

    store["entries"][rel] = {
        "hash": current_hash,
        "trusted_at": datetime.now(timezone.utc).isoformat(),
    }
    _save_store(root, store)

    return TrustResult(
        path=path,
        status="trusted",
        current_hash=current_hash,
        stored_hash=current_hash,
        trusted_at=store["entries"][rel]["trusted_at"],
    )


def untrust_file(path: Path, root: Path | None = None) -> bool:
    """Remove path from the trust store. Returns True if it was present."""
    if root is None:
        root = _find_repo_root(path)

    store = _load_store(root)
    try:
        rel = str(path.relative_to(root))
    except ValueError:
        rel = str(path)

    if rel in store["entries"]:
        del store["entries"][rel]
        _save_store(root, store)
        return True
    return False


def verify_all_skills(root: Path) -> list[TrustResult]:
    """Verify all *.skill.md files found under root against the trust store."""
    from agentmd.parser import find_all_agentmd_files, parse_file
    from agentmd.models import SkillFile

    results: list[TrustResult] = []
    for fpath in find_all_agentmd_files(root):
        try:
            parsed = parse_file(fpath)
        except Exception:
            continue
        if isinstance(parsed, SkillFile):
            results.append(verify(fpath, root=root))
    return results
