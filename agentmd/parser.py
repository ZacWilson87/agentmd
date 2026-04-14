"""YAML frontmatter extraction and file parsing/validation."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from agentmd.models import AgentMDFile, AgentsFile, RuleFile, SkillFile

# Matches an opening --- block optionally preceded by whitespace/BOM
_FRONTMATTER_RE = re.compile(
    r"^\s*---\s*\n(.*?)\n---\s*(?:\n|$)",
    re.DOTALL,
)

# File name patterns that identify agentmd files
_AGENTS_NAMES = {"AGENTS.md"}
_SKILL_SUFFIX = ".skill.md"
_RULE_SUFFIX = ".rule.md"


class ParseError(Exception):
    """Raised when an agentmd file cannot be parsed or fails validation."""


def extract_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Extract YAML frontmatter from Markdown text.

    Returns (frontmatter_dict, body_markdown).
    Raises ParseError if no valid frontmatter block is found.
    """
    match = _FRONTMATTER_RE.match(text)
    if not match:
        raise ParseError("No valid YAML frontmatter block found (expected --- ... ---)")

    raw_yaml = match.group(1)
    body = text[match.end():]

    try:
        data = yaml.safe_load(raw_yaml)
    except yaml.YAMLError as exc:
        raise ParseError(f"YAML parse error in frontmatter: {exc}") from exc

    if not isinstance(data, dict):
        raise ParseError("Frontmatter must be a YAML mapping (key: value pairs)")

    return data, body


def _file_type(path: Path) -> str | None:
    """Return 'agents', 'skill', or 'rule' based on filename, or None if not agentmd."""
    name = path.name
    if name in _AGENTS_NAMES:
        return "agents"
    if name.endswith(_SKILL_SUFFIX):
        return "skill"
    if name.endswith(_RULE_SUFFIX):
        return "rule"
    return None


def parse_file(path: Path) -> AgentMDFile:
    """Parse and validate an agentmd file.

    Returns the appropriate model instance (AgentsFile | SkillFile | RuleFile).
    Raises ParseError with a descriptive message on failure.
    """
    if not path.exists():
        raise ParseError(f"File not found: {path}")
    if not path.is_file():
        raise ParseError(f"Not a file: {path}")

    text = path.read_text(encoding="utf-8")

    try:
        data, _body = extract_frontmatter(text)
    except ParseError as exc:
        raise ParseError(f"{path}: {exc}") from exc

    # Determine file type from path, falling back to 'type' field in data
    inferred = _file_type(path)
    declared = data.get("type")

    if inferred and declared and inferred != declared:
        raise ParseError(
            f"{path}: filename implies type '{inferred}' but frontmatter declares type '{declared}'"
        )

    file_type = inferred or declared
    if file_type is None:
        raise ParseError(
            f"{path}: cannot determine file type — filename is not AGENTS.md / *.skill.md / *.rule.md "
            "and no 'type' field in frontmatter"
        )

    model_map = {
        "agents": AgentsFile,
        "skill": SkillFile,
        "rule": RuleFile,
    }
    model_cls = model_map.get(file_type)
    if model_cls is None:
        raise ParseError(f"{path}: unknown type '{file_type}'")

    try:
        return model_cls.model_validate(data)
    except ValidationError as exc:
        # Flatten pydantic errors into a human-readable string
        messages = []
        for err in exc.errors():
            loc = ".".join(str(l) for l in err["loc"])
            messages.append(f"  field '{loc}': {err['msg']}")
        raise ParseError(f"{path}: validation failed\n" + "\n".join(messages)) from exc


def find_all_agentmd_files(root: Path) -> list[Path]:
    """Walk root recursively and return all agentmd files, sorted."""
    found: list[Path] = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and _file_type(path) is not None:
            found.append(path)
    return found
