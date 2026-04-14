#!/usr/bin/env python3
"""Generate .cursor/rules/*.mdc files from agentmd export JSON.

Usage:
    agentmd export <file-or-dir> | python3 scripts/generate-cursor-rules.py

Creates:
    .cursor/rules/project-context.mdc   — always-on project context (alwaysApply: true)
    .cursor/rules/<rule-id>.mdc         — one file per active rule, auto-attached by glob

Add to Makefile or pre-commit to keep .cursor/rules/ in sync with agentmd files.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys


def main() -> None:
    data = json.load(sys.stdin)
    rules_dir = pathlib.Path(".cursor/rules")
    rules_dir.mkdir(parents=True, exist_ok=True)
    generated: list[str] = []

    # Always-on project context rule
    if data.get("agents_file"):
        a = data["agents_file"]
        lines = [
            "---",
            "description: Project conventions and AI agent instructions",
            "globs: ",
            "alwaysApply: true",
            "---",
            "",
        ]
        if a.get("agent_instructions"):
            lines.append(a["agent_instructions"].rstrip())
            lines.append("")
        if a.get("conventions"):
            lines.append("## Conventions")
            for c in a["conventions"]:
                lines.append(f"- {c}")
            lines.append("")
        if a.get("stack"):
            lines.append(f"## Stack\n{', '.join(a['stack'])}")
        (rules_dir / "project-context.mdc").write_text("\n".join(lines))
        generated.append("project-context.mdc")

    # Per-rule files (auto-attached by glob)
    for rule in data.get("active_rules", []):
        globs = ", ".join(rule.get("applies_to", []))
        lines = [
            "---",
            f"description: [{rule['severity'].upper()}] {rule['description']}",
            f"globs: {globs}",
            "alwaysApply: false",
            "---",
            "",
            f"# {rule['id']}",
            "",
            rule.get("description", ""),
        ]
        if rule.get("rationale"):
            lines.extend(["", f"**Rationale**: {rule['rationale']}"])
        fname = re.sub(r"[^a-z0-9-]", "-", rule["id"].lower()) + ".mdc"
        (rules_dir / fname).write_text("\n".join(lines))
        generated.append(fname)

    print(f"Generated {len(generated)} file(s) in .cursor/rules/:")
    for name in generated:
        print(f"  {name}")


if __name__ == "__main__":
    main()
