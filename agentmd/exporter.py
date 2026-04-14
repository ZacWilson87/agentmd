"""JSON export for tool integration (Claude Code hooks, Cursor, etc.)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agentmd.resolver import ResolvedContext


def export_context(ctx: ResolvedContext) -> dict[str, Any]:
    """Serialise a ResolvedContext to a plain dict suitable for JSON export."""
    return {
        "agents_file": _export_agents(ctx.agents_file) if ctx.agents_file else None,
        "active_skills": [_export_skill(s, ctx.skill_paths.get(s.id)) for s in ctx.active_skills],
        "active_rules": [_export_rule(r) for r in ctx.active_rules],
        "source_files": [str(p) for p in ctx.source_files],
        # Additive merges from all AGENTS.md files in scope
        "merged_stack": ctx.merged_stack,
        "merged_conventions": ctx.merged_conventions,
        # Concise per-skill instructions for direct agent consumption.
        # Each entry is a self-contained prompt snippet an agent can act on.
        "prompt_snippets": ctx.prompt_snippets,
        # Non-fatal warnings from resolution (skipped broken files, duplicate refs).
        "warnings": ctx.warnings,
    }


def _export_agents(a: Any) -> dict[str, Any]:
    return {
        "agentmd": a.agentmd,
        "type": a.type,
        "scope": a.scope,
        "name": a.name,
        "stack": a.stack,
        "conventions": a.conventions,
        "skills": a.skills,
        "rules": a.rules,
        "agent_instructions": a.agent_instructions,
    }


def _export_skill(s: Any, path: Path | None = None) -> dict[str, Any]:
    return {
        "agentmd": s.agentmd,
        "type": s.type,
        "id": s.id,
        "version": s.version,
        "description": s.description,
        "trigger": s.trigger,
        "inputs": [i.model_dump() for i in s.inputs],
        "outputs": s.outputs,
        "tags": s.tags,
        "path": str(path) if path else None,
    }


def _export_rule(r: Any) -> dict[str, Any]:
    return {
        "agentmd": r.agentmd,
        "type": r.type,
        "id": r.id,
        "severity": r.severity,
        "description": r.description,
        "rationale": r.rationale,
        "applies_to": r.applies_to,
        "exceptions": r.exceptions,
        "immutable": r.immutable,
    }
