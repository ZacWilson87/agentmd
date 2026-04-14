#!/usr/bin/env python3
"""Generate .windsurf/rules/ and .windsurf/workflows/ from agentmd export JSON.

Usage:
    agentmd export <file-or-dir> | python3 scripts/generate-windsurf.py

Creates:
    .windsurf/rules/<rule-id>.md      — one file per active rule
    .windsurf/workflows/<skill-id>.md — one file per active skill (slash-command invocable)

Rule trigger mapping:
    Rule with applies_to globs → trigger: glob
    Rule with applies_to ["**/*"] only → trigger: always_on

Windsurf natively reads AGENTS.md (root = always_on, subdirectory = auto-glob-scoped),
so no AGENTS.md conversion is needed — that file is used directly.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys


def main() -> None:
    data = json.load(sys.stdin)
    rules_dir = pathlib.Path(".windsurf/rules")
    workflows_dir = pathlib.Path(".windsurf/workflows")
    rules_dir.mkdir(parents=True, exist_ok=True)
    workflows_dir.mkdir(parents=True, exist_ok=True)
    generated_rules: list[str] = []
    generated_workflows: list[str] = []

    # Rules
    for rule in data.get("active_rules", []):
        applies_to = rule.get("applies_to", ["**/*"])
        is_catch_all = applies_to == ["**/*"]

        if is_catch_all:
            trigger = "always_on"
            frontmatter = ["---", f"trigger: {trigger}", f"description: \"{rule['description']}\"", "---", ""]
        else:
            globs = ", ".join(f'"{g}"' for g in applies_to)
            trigger = "glob"
            frontmatter = ["---", f"trigger: {trigger}", f"globs: {globs}", f"description: \"{rule['description']}\"", "---", ""]

        lines = frontmatter + [
            f"# {rule['id']} [{rule['severity'].upper()}]",
            "",
            rule.get("description", ""),
        ]
        if rule.get("rationale"):
            lines.extend(["", f"**Rationale**: {rule['rationale']}"])

        fname = re.sub(r"[^a-z0-9-]", "-", rule["id"].lower()) + ".md"
        (rules_dir / fname).write_text("\n".join(lines))
        generated_rules.append(fname)

    # Workflows (skills)
    for skill in data.get("active_skills", []):
        body_lines = [
            f"# {skill['id']}",
            "",
            skill.get("description", ""),
            "",
            f"**Trigger**: {skill.get('trigger', '')}",
            "",
        ]

        skill_path = skill.get("path")
        if skill_path:
            src = pathlib.Path(skill_path)
            if src.exists():
                body_lines.append(src.read_text())

        fname = re.sub(r"[^a-z0-9-]", "-", skill["id"].lower()) + ".md"
        (workflows_dir / fname).write_text("\n".join(body_lines))
        generated_workflows.append(fname)

    if generated_rules:
        print(f"Generated {len(generated_rules)} rule file(s) in .windsurf/rules/:")
        for name in generated_rules:
            print(f"  {name}")

    if generated_workflows:
        print(f"Generated {len(generated_workflows)} workflow file(s) in .windsurf/workflows/:")
        for name in generated_workflows:
            print(f"  {name}")


if __name__ == "__main__":
    main()
