#!/usr/bin/env python3
"""Generate .github/copilot-instructions.md from agentmd export JSON.

Usage:
    agentmd export <file-or-dir> | python3 scripts/generate-copilot-instructions.py \
        > .github/copilot-instructions.md

Notes:
  - Copilot code review reads only the first 4,000 characters; content beyond
    that is silently ignored. This script emits a warning if the output exceeds
    that limit.
  - For path-scoped instructions (Copilot cloud agent + code review), see the
    inline snippet in docs/integrations.md for generating
    .github/instructions/*.instructions.md files from active_rules.
"""
from __future__ import annotations

import json
import sys

REVIEW_CHAR_LIMIT = 4000


def main() -> None:
    data = json.load(sys.stdin)
    lines: list[str] = []

    a = data.get("agents_file")
    if a:
        if a.get("agent_instructions"):
            lines.append(a["agent_instructions"].strip())
            lines.append("")
        if a.get("stack"):
            lines.append(f"## Stack\n{', '.join(a['stack'])}")
            lines.append("")
        if a.get("conventions"):
            lines.append("## Conventions")
            for c in a["conventions"]:
                lines.append(f"- {c}")
            lines.append("")

    for rule in data.get("active_rules", []):
        lines.append(f"## {rule['id']} [{rule['severity'].upper()}]")
        lines.append(rule.get("description", ""))
        if rule.get("rationale"):
            lines.append(f"> {rule['rationale']}")
        lines.append("")

    output = "\n".join(lines)
    print(output)

    if len(output) > REVIEW_CHAR_LIMIT:
        char_count = len(output)
        print(
            f"\n<!-- WARNING: {char_count} chars — Copilot code review reads only "
            f"the first {REVIEW_CHAR_LIMIT}. Consider splitting rules into "
            f".github/instructions/*.instructions.md files. -->",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
