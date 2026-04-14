"""Scope resolution algorithm — the core logic of agentmd."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from agentmd.models import AgentsFile, RuleFile, SkillFile
from agentmd.parser import ParseError, parse_file
from agentmd.utils import rule_applies_to_path


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


# ---------------------------------------------------------------------------
# Rule-applies helper (delegates to utils)
# ---------------------------------------------------------------------------


def _rule_applies(rule: RuleFile, target: Path) -> bool:
    return rule_applies_to_path(rule.applies_to, rule.exceptions, target)


# ---------------------------------------------------------------------------
# Directory-level collectors
# ---------------------------------------------------------------------------


def _collect_skills_in_dir(directory: Path) -> list[SkillFile]:
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
            pass
    return skills


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


def _collect_referenced_skills(agents: AgentsFile, agents_path: Path) -> list[tuple[Path, SkillFile]]:
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
    """
    ctx = ResolvedContext()
    start_dir = target if target.is_dir() else target.parent

    # Walk up from start_dir
    current = start_dir
    agents_found = False
    scope_depth = 0

    # Track IDs seen for skills
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

                        # Referenced skills from AGENTS.md
                        for fpath, skill in _collect_referenced_skills(parsed, agents_path):
                            if skill.id not in seen_skill_ids:
                                ctx.active_skills.append(skill)
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

            except ParseError:
                pass  # Conservative: skip broken AGENTS.md

        # --- skills/ subdirectory ---
        for skill in _collect_skills_in_dir(current):
            if skill.id not in seen_skill_ids:
                ctx.active_skills.append(skill)
                seen_skill_ids.add(skill.id)
                ctx.source_files.append(current / "skills")

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

    # Deduplicate source_files while preserving order
    seen: set[Path] = set()
    deduped: list[Path] = []
    for p in ctx.source_files:
        if p not in seen:
            seen.add(p)
            deduped.append(p)
    ctx.source_files = deduped

    return ctx
