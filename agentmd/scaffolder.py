"""init + add commands: template generation and AGENTS.md auto-registration."""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from jinja2 import Environment, PackageLoader, select_autoescape

from agentmd.parser import ParseError, extract_frontmatter

_TEMPLATES_DIR = Path(__file__).parent / "templates"

_jinja_env = Environment(
    loader=PackageLoader("agentmd", "templates"),
    autoescape=select_autoescape([]),
    keep_trailing_newline=True,
)


def _render_template(template_name: str, **ctx: object) -> str:
    tmpl = _jinja_env.get_template(template_name)
    return tmpl.render(**ctx)


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------


def init_repo(directory: Path, *, force: bool = False) -> list[Path]:
    """Create AGENTS.md, skills/, and rules/ in directory.

    Returns list of paths that were created.
    Skips existing files unless force=True.
    """
    created: list[Path] = []
    agents_path = directory / "AGENTS.md"

    if force or not agents_path.exists():
        project_name = directory.name.replace("-", " ").replace("_", " ").title()
        content = _render_template("AGENTS.md.jinja", name=project_name)
        agents_path.write_text(content, encoding="utf-8")
        created.append(agents_path)

    for subdir in ("skills", "rules"):
        d = directory / subdir
        d.mkdir(exist_ok=True)
        gitkeep = d / ".gitkeep"
        if force or not gitkeep.exists():
            gitkeep.write_text("", encoding="utf-8")
            created.append(gitkeep)

    return created


# ---------------------------------------------------------------------------
# add skill
# ---------------------------------------------------------------------------


def add_skill(skill_id: str, directory: Path, *, register: bool = True) -> Path:
    """Scaffold a new *.skill.md file and optionally register it in AGENTS.md.

    Returns the path of the created file.
    """
    _validate_kebab(skill_id)
    skills_dir = directory / "skills"
    skills_dir.mkdir(exist_ok=True)

    out_path = skills_dir / f"{skill_id}.skill.md"
    description = skill_id.replace("-", " ").title()
    content = _render_template("skill.md.jinja", id=skill_id, description=description)
    out_path.write_text(content, encoding="utf-8")

    if register:
        _register_in_agents(directory, "skills", f"skills/{skill_id}.skill.md")

    return out_path


# ---------------------------------------------------------------------------
# add rule
# ---------------------------------------------------------------------------


def add_rule(rule_id: str, directory: Path, *, register: bool = True) -> Path:
    """Scaffold a new *.rule.md file and optionally register it in AGENTS.md.

    Returns the path of the created file.
    """
    _validate_kebab(rule_id)
    rules_dir = directory / "rules"
    rules_dir.mkdir(exist_ok=True)

    out_path = rules_dir / f"{rule_id}.rule.md"
    description = rule_id.replace("-", " ").title()
    content = _render_template("rule.md.jinja", id=rule_id, description=description)
    out_path.write_text(content, encoding="utf-8")

    if register:
        _register_in_agents(directory, "rules", f"rules/{rule_id}.rule.md")

    return out_path


# ---------------------------------------------------------------------------
# AGENTS.md auto-registration
# ---------------------------------------------------------------------------


def _find_nearest_agents(start: Path) -> Path | None:
    """Walk up from start to find the nearest AGENTS.md."""
    current = start
    while True:
        candidate = current / "AGENTS.md"
        if candidate.is_file():
            return candidate
        parent = current.parent
        if parent == current:
            return None
        current = parent


def _register_in_agents(start: Path, list_key: str, rel_path: str) -> None:
    """Add rel_path to the skills or rules list in the nearest AGENTS.md.

    Conservative: if AGENTS.md cannot be parsed or updated safely, silently skip.
    """
    agents_path = _find_nearest_agents(start)
    if agents_path is None:
        return

    text = agents_path.read_text(encoding="utf-8")
    try:
        data, body = extract_frontmatter(text)
    except ParseError:
        return  # Don't corrupt existing files

    entries: list[str] = data.get(list_key, []) or []
    if rel_path in entries:
        return  # Already registered

    entries.append(rel_path)
    data[list_key] = entries

    # Reconstruct the file: replace frontmatter, preserve body
    new_frontmatter = yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False)
    new_text = f"---\n{new_frontmatter}---\n{body}"
    agents_path.write_text(new_text, encoding="utf-8")


def _validate_kebab(id_str: str) -> None:
    if not re.match(r"^[a-z0-9]+(-[a-z0-9]+)*$", id_str):
        raise ValueError(f"ID must be kebab-case (lowercase letters, digits, hyphens): '{id_str}'")
