"""Scope resolution algorithm — the core logic of agentmd."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from agentmd.models import AgentsFile, RuleFile, SkillFile
from agentmd.parser import ParseError, parse_file
from agentmd.utils import rule_applies_to_path


class CircularSkillError(Exception):
    """Raised when circular or duplicate skill references are detected."""


@dataclass
class ResolvedContext:
    """The merged agentmd context for a given target file path."""

    agents_file: AgentsFile | None = None
    active_skills: list[SkillFile] = field(default_factory=list)
    active_rules: list[RuleFile] = field(default_factory=list)
    source_files: list[Path] = field(default_factory=list)

    # Additive merges across all AGENTS.md files encountered on the walk path
    # (closest-scope values first).  Useful for monorepos where multiple
    # AGENTS.md files each declare part of the overall stack.
    merged_stack: list[str] = field(default_factory=list)
    merged_conventions: list[str] = field(default_factory=list)

    # Map of skill ID → source file path, populated during resolution.
    # Used to generate prompt_snippets and for diagnostic output.
    skill_paths: dict[str, Path] = field(default_factory=dict)

    # Concise per-skill prompt snippets for direct injection into agent context.
    # Format: "You have access to the [id] procedure. To use it, follow the
    # steps in [path]. Trigger: [trigger]."
    prompt_snippets: list[str] = field(default_factory=list)

    # Non-fatal warnings collected during resolution (e.g. skipped broken files,
    # duplicate skill references).  Surfaced by CLI and MCP but never fatal.
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Rule-applies helper (delegates to utils)
# ---------------------------------------------------------------------------


def _rule_applies(rule: RuleFile, target: Path) -> bool:
    return rule_applies_to_path(rule.applies_to, rule.exceptions, target)


# ---------------------------------------------------------------------------
# Directory-level collectors
# ---------------------------------------------------------------------------


def _collect_skills_in_dir(directory: Path) -> list[tuple[SkillFile, Path]]:
    """Return (SkillFile, path) pairs from directory/skills/*.skill.md."""
    skills_dir = directory / "skills"
    if not skills_dir.is_dir():
        return []
    result: list[tuple[SkillFile, Path]] = []
    for fpath in sorted(skills_dir.glob("*.skill.md")):
        try:
            parsed = parse_file(fpath)
            if isinstance(parsed, SkillFile):
                result.append((parsed, fpath))
        except ParseError:
            pass
    return result


def _collect_rules_in_dir(directory: Path) -> list[RuleFile]:
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


def _collect_referenced_skills(
    agents: AgentsFile,
    agents_path: Path,
    visited_paths: set[Path],
    warnings: list[str],
) -> list[tuple[Path, SkillFile]]:
    """Load skills explicitly listed in AGENTS.md's skills array.

    Detects duplicate/circular references within the same AGENTS.md by
    tracking visited_paths.  Duplicates emit a warning and are skipped.
    """
    base = agents_path.parent
    result: list[tuple[Path, SkillFile]] = []
    for rel_path in agents.skills:
        fpath = (base / rel_path).resolve()
        if not fpath.exists():
            continue
        # Guard: same absolute path referenced more than once in this AGENTS.md
        if fpath in visited_paths:
            warnings.append(
                f"Duplicate skill reference skipped: {fpath} "
                f"(referenced again in {agents_path})"
            )
            continue
        visited_paths.add(fpath)
        try:
            parsed = parse_file(fpath)
            if isinstance(parsed, SkillFile):
                result.append((fpath, parsed))
        except ParseError as exc:
            warnings.append(f"Skipped unreadable skill file {fpath}: {exc}")
    return result


def _collect_referenced_rules(agents: AgentsFile, agents_path: Path) -> list[tuple[Path, RuleFile]]:
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


# ---------------------------------------------------------------------------
# Immutable-aware rule deduplication
# ---------------------------------------------------------------------------


def _deduplicate_rules(
    raw_rules: list[tuple[RuleFile, int]],
) -> list[RuleFile]:
    """Deduplicate rules by ID with immutable-priority semantics.

    raw_rules is a list of (rule, scope_depth) where scope_depth=0 is closest.

    Resolution order for each unique ID:
    1. Immutable rules take priority over non-immutable rules regardless of scope.
    2. Among multiple immutable rules with the same ID, closest scope wins.
    3. Among multiple non-immutable rules with the same ID, closest scope wins
       (standard first-encountered behaviour).
    """
    # Group by ID; track (rule, depth, is_immutable)
    groups: dict[str, list[tuple[RuleFile, int]]] = {}
    for rule, depth in raw_rules:
        groups.setdefault(rule.id, []).append((rule, depth))

    result: list[tuple[RuleFile, int]] = []
    for _id, candidates in groups.items():
        immutable_candidates = [(r, d) for r, d in candidates if r.immutable]
        if immutable_candidates:
            # Pick the closest immutable rule
            winner = min(immutable_candidates, key=lambda x: x[1])
        else:
            # Pick the closest non-immutable rule
            winner = min(candidates, key=lambda x: x[1])
        result.append(winner)

    # Sort by original scope depth to preserve closest-first ordering
    result.sort(key=lambda x: x[1])
    return [r for r, _ in result]


# ---------------------------------------------------------------------------
# Prompt snippet generator
# ---------------------------------------------------------------------------


def _build_prompt_snippets(
    skills: list[SkillFile],
    skill_paths: dict[str, Path],
) -> list[str]:
    """Generate a concise prompt snippet for each active skill.

    Format:
      "You have access to the [id] procedure. To use it, follow the steps in
       [path/to/skill.md]. Trigger: [trigger_condition]."
    """
    snippets: list[str] = []
    for skill in skills:
        path = skill_paths.get(skill.id)
        path_str = str(path) if path else "unknown"
        snippets.append(
            f"You have access to the [{skill.id}] procedure. "
            f"To use it, follow the steps in [{path_str}]. "
            f"Trigger: {skill.trigger}"
        )
    return snippets


# ---------------------------------------------------------------------------
# Main resolver
# ---------------------------------------------------------------------------


def resolve(target: Path) -> ResolvedContext:
    """Resolve agentmd context for target file path.

    Algorithm:
    1. Start at target's directory.
    2. Walk UP toward filesystem root.
    3. At each level collect:
       a. AGENTS.md — closest wins for name/scope/agent_instructions;
          stack and conventions accumulate additively across ALL AGENTS.md files.
       b. skills/ subdirectory — accumulate all *.skill.md (closest-scope first).
       c. rules/ subdirectory — accumulate all *.rule.md (closest-scope first,
          but immutable rules from any scope cannot be displaced).
    4. Resolve referenced skills/rules from AGENTS.md paths.
    5. Filter rules by applies_to globs against target_file_path.
    6. Return merged ResolvedContext.

    Safety:
    - Duplicate AGENTS.md skill references within a single file are detected and
      surfaced as warnings (stored in ctx.warnings), not hard errors.
    - ParseErrors on rule/skill files are silently skipped during resolution
      (reported by `agentmd validate`); the skipped path is added to ctx.warnings.
    - Circular skill dependencies cannot occur in v1.0 because SkillFile does not
      reference other SkillFile paths.  The guard in _collect_referenced_skills
      protects against the degenerate case of a path listed twice in AGENTS.md.
    """
    ctx = ResolvedContext()
    start_dir = target if target.is_dir() else target.parent

    # Walk up from start_dir
    current = start_dir
    agents_found = False
    scope_depth = 0

    # Track IDs seen for skills (closest-scope wins)
    seen_skill_ids: set[str] = set()

    # Collect raw (rule, depth) tuples for deduplication post-walk
    raw_rules: list[tuple[RuleFile, int]] = []
    seen_referenced_rule_ids: set[str] = set()

    # Accumulated stack / conventions from all AGENTS.md files
    all_stacks: list[str] = []
    all_conventions: list[str] = []

    while True:
        # --- AGENTS.md ---
        agents_path = current / "AGENTS.md"
        if agents_path.is_file():
            try:
                parsed = parse_file(agents_path)
                if isinstance(parsed, AgentsFile):
                    # Closest AGENTS.md → use as primary agents_file
                    if not agents_found:
                        ctx.agents_file = parsed
                        ctx.source_files.append(agents_path)
                        agents_found = True

                        # Track visited skill paths within this AGENTS.md to
                        # detect duplicate/circular references.
                        _visited_ref_paths: set[Path] = set()

                        # Referenced skills from AGENTS.md
                        for fpath, skill in _collect_referenced_skills(
                            parsed, agents_path, _visited_ref_paths, ctx.warnings
                        ):
                            if skill.id not in seen_skill_ids:
                                ctx.active_skills.append(skill)
                                ctx.skill_paths[skill.id] = fpath
                                ctx.source_files.append(fpath)
                                seen_skill_ids.add(skill.id)

                        # Referenced rules from AGENTS.md
                        for fpath, rule in _collect_referenced_rules(parsed, agents_path):
                            if rule.id not in seen_referenced_rule_ids:
                                raw_rules.append((rule, scope_depth))
                                ctx.source_files.append(fpath)
                                seen_referenced_rule_ids.add(rule.id)

                    # Additive merge: collect stack + conventions from ALL AGENTS.md
                    for item in parsed.stack:
                        if item not in all_stacks:
                            all_stacks.append(item)
                    for item in parsed.conventions:
                        if item not in all_conventions:
                            all_conventions.append(item)

            except ParseError as exc:
                ctx.warnings.append(f"Skipped unreadable AGENTS.md at {agents_path}: {exc}")

        # --- skills/ subdirectory ---
        for skill, fpath in _collect_skills_in_dir(current):
            if skill.id not in seen_skill_ids:
                ctx.active_skills.append(skill)
                ctx.skill_paths[skill.id] = fpath
                seen_skill_ids.add(skill.id)
                ctx.source_files.append(fpath)

        # --- rules/ subdirectory ---
        for rule in _collect_rules_in_dir(current):
            raw_rules.append((rule, scope_depth))

        # Move up
        parent = current.parent
        if parent == current:
            break
        current = parent
        scope_depth += 1

    # Deduplicate rules (immutable-aware)
    all_rules = _deduplicate_rules(raw_rules)

    # Filter rules for the target path
    if not target.is_dir():
        ctx.active_rules = [r for r in all_rules if _rule_applies(r, target)]
    else:
        ctx.active_rules = all_rules

    # Store additive merges
    ctx.merged_stack = all_stacks
    ctx.merged_conventions = all_conventions

    # Generate prompt snippets for every active skill
    ctx.prompt_snippets = _build_prompt_snippets(ctx.active_skills, ctx.skill_paths)

    # Deduplicate source_files while preserving order
    seen: set[Path] = set()
    deduped: list[Path] = []
    for p in ctx.source_files:
        if p not in seen:
            seen.add(p)
            deduped.append(p)
    ctx.source_files = deduped

    return ctx
