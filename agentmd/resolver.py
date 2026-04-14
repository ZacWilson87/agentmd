"""Scope resolution algorithm — the core logic of agentmd."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from agentmd.models import AgentsFile, RuleFile, SkillFile
from agentmd.parser import ParseError, parse_file


@dataclass
class ResolvedContext:
    """The merged agentmd context for a given target file path."""

    agents_file: AgentsFile | None = None
    active_skills: list[SkillFile] = field(default_factory=list)
    active_rules: list[RuleFile] = field(default_factory=list)
    source_files: list[Path] = field(default_factory=list)


def _path_matches_pattern(pattern: str, path: Path) -> bool:
    """Return True if path matches a glob pattern.

    Tries matching against:
    1. The full absolute path string (for absolute patterns)
    2. All trailing subpaths of increasing depth (for relative patterns like
       "agentmd/**/*.py" or "**/*.py")
    3. The filename alone (for simple patterns like "*.py")
    """
    import fnmatch

    path_str = str(path)
    path_name = path.name

    # Direct match on full path or filename
    if fnmatch.fnmatch(path_str, pattern) or fnmatch.fnmatch(path_name, pattern):
        return True

    # Try all trailing portions of the path: e.g. for /a/b/c/d.py try:
    #   a/b/c/d.py, b/c/d.py, c/d.py, d.py
    parts = path.parts
    for i in range(len(parts)):
        sub = "/".join(parts[i:])
        if fnmatch.fnmatch(sub, pattern):
            return True

    return False


def _rule_applies(rule: RuleFile, target: Path) -> bool:
    """Return True if rule applies to target path (after exception filtering)."""
    def matches_any(patterns: list[str]) -> bool:
        return any(_path_matches_pattern(pat, target) for pat in patterns)

    if not matches_any(rule.applies_to):
        return False
    if matches_any(rule.exceptions):
        return False
    return True


def _collect_skills_in_dir(directory: Path) -> list[SkillFile]:
    """Collect all *.skill.md files from a /skills subdirectory."""
    skills_dir = directory / "skills"
    if not skills_dir.is_dir():
        return []

    skills: list[SkillFile] = []
    for fpath in sorted(skills_dir.glob("*.skill.md")):
        try:
            parsed = parse_file(fpath)
            if isinstance(parsed, SkillFile):
                skills.append(parsed)
        except ParseError:
            pass  # Conservative: skip broken files, don't abort resolution
    return skills


def _collect_rules_in_dir(directory: Path) -> list[RuleFile]:
    """Collect all *.rule.md files from a /rules subdirectory."""
    rules_dir = directory / "rules"
    if not rules_dir.is_dir():
        return []

    rules: list[RuleFile] = []
    for fpath in sorted(rules_dir.glob("*.rule.md")):
        try:
            parsed = parse_file(fpath)
            if isinstance(parsed, RuleFile):
                rules.append(parsed)
        except ParseError:
            pass
    return rules


def _collect_referenced_skills(agents: AgentsFile, agents_path: Path) -> list[tuple[Path, SkillFile]]:
    """Load skill files explicitly referenced in AGENTS.md's skills list."""
    base = agents_path.parent
    result: list[tuple[Path, SkillFile]] = []
    for rel_path in agents.skills:
        fpath = (base / rel_path).resolve()
        if not fpath.exists():
            continue
        try:
            parsed = parse_file(fpath)
            if isinstance(parsed, SkillFile):
                result.append((fpath, parsed))
        except ParseError:
            pass
    return result


def _collect_referenced_rules(agents: AgentsFile, agents_path: Path) -> list[tuple[Path, RuleFile]]:
    """Load rule files explicitly referenced in AGENTS.md's rules list."""
    base = agents_path.parent
    result: list[tuple[Path, RuleFile]] = []
    for rel_path in agents.rules:
        fpath = (base / rel_path).resolve()
        if not fpath.exists():
            continue
        try:
            parsed = parse_file(fpath)
            if isinstance(parsed, RuleFile):
                result.append((fpath, parsed))
        except ParseError:
            pass
    return result


def resolve(target: Path) -> ResolvedContext:
    """Resolve agentmd context for target file path.

    Algorithm:
    1. Start at target's directory.
    2. Walk UP toward filesystem root.
    3. At each level collect:
       a. AGENTS.md — stop after first found (closest wins).
       b. skills/ subdirectory — accumulate all *.skill.md (closest-scope first).
       c. rules/ subdirectory — accumulate all *.rule.md (closest-scope first).
    4. Resolve referenced skills/rules from AGENTS.md paths.
    5. Filter rules by applies_to globs.
    6. Return merged ResolvedContext.
    """
    ctx = ResolvedContext()

    start_dir = target if target.is_dir() else target.parent

    # Walk up from start_dir to filesystem root
    current = start_dir
    agents_found = False

    # Track IDs to avoid duplicates when accumulating across scopes
    seen_skill_ids: set[str] = set()
    seen_rule_ids: set[str] = set()

    while True:
        # --- AGENTS.md (stop at first found) ---
        agents_path = current / "AGENTS.md"
        if not agents_found and agents_path.is_file():
            try:
                parsed = parse_file(agents_path)
                if isinstance(parsed, AgentsFile):
                    ctx.agents_file = parsed
                    ctx.source_files.append(agents_path)
                    agents_found = True

                    # Load referenced skills from AGENTS.md
                    for fpath, skill in _collect_referenced_skills(parsed, agents_path):
                        if skill.id not in seen_skill_ids:
                            ctx.active_skills.append(skill)
                            ctx.source_files.append(fpath)
                            seen_skill_ids.add(skill.id)

                    # Load referenced rules from AGENTS.md
                    for fpath, rule in _collect_referenced_rules(parsed, agents_path):
                        if rule.id not in seen_rule_ids:
                            ctx.active_rules.append(rule)
                            ctx.source_files.append(fpath)
                            seen_rule_ids.add(rule.id)

            except ParseError:
                pass  # Conservative: skip broken AGENTS.md, keep walking

        # --- skills/ subdirectory ---
        for skill in _collect_skills_in_dir(current):
            if skill.id not in seen_skill_ids:
                ctx.active_skills.append(skill)
                seen_skill_ids.add(skill.id)
                ctx.source_files.append(current / "skills")

        # --- rules/ subdirectory ---
        for rule in _collect_rules_in_dir(current):
            if rule.id not in seen_rule_ids:
                ctx.active_rules.append(rule)
                seen_rule_ids.add(rule.id)
                ctx.source_files.append(current / "rules")

        # Move up
        parent = current.parent
        if parent == current:
            break  # Reached filesystem root
        current = parent

    # Filter rules: keep only those whose applies_to patterns match the target
    if not target.is_dir():
        ctx.active_rules = [r for r in ctx.active_rules if _rule_applies(r, target)]

    # Deduplicate source_files while preserving order
    seen: set[Path] = set()
    deduped: list[Path] = []
    for p in ctx.source_files:
        if p not in seen:
            seen.add(p)
            deduped.append(p)
    ctx.source_files = deduped

    return ctx
