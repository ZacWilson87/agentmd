# agentmd Integrations

How to wire agentmd into your AI coding tools.

---

## MCP Server (recommended)

agentmd ships a built-in MCP server that exposes all resolution, checking,
and audit functionality as MCP tools over JSON-RPC 2.0 on stdio. This is
the preferred integration: the agent calls tools directly instead of parsing
hook stdout.

### Setup

1. Install agentmd:
   ```bash
   pip install agentmd
   ```

2. Add agentmd to your MCP configuration. For Claude Code, add to
   `.mcp.json` (project-scoped) or `~/.claude/settings.json` (user-scoped):
   ```json
   {
     "mcpServers": {
       "agentmd": {
         "command": "agentmd",
         "args": ["mcp", "--root", "/absolute/path/to/your/project"]
       }
     }
   }
   ```

   For Windsurf, add to `~/.codeium/windsurf/mcp_config.json` (global only;
   Windsurf does not support project-level MCP config):
   ```json
   {
     "mcpServers": {
       "agentmd": {
         "command": "agentmd",
         "args": ["mcp", "--root", "/absolute/path/to/your/project"]
       }
     }
   }
   ```

3. The agent now has access to these tools:

   | Tool | Description |
   |------|-------------|
   | `agentmd_resolve` | Resolve context (AGENTS.md, skills, rules, **prompt snippets**) for a file |
   | `agentmd_list_skills` | List all SKILL.md files under the repo root |
   | `agentmd_list_rules` | List all RULE.md files under the repo root |
   | `agentmd_validate` | Validate all agentmd files — returns pass/fail per file |
   | `agentmd_check` | Check a file for rule violations with line numbers |
   | `agentmd_audit` | Full audit: validate + check + drift + trust |

### Prompt Snippets

Every `agentmd_resolve` call returns a `prompt_snippets` array — one entry
per active skill — in this format:

```
You have access to the [scaffold-endpoint] procedure. To use it, follow the
steps in [/repo/skills/scaffold-endpoint.skill.md]. Trigger: when asked to
scaffold a new API endpoint
```

The agent can read these directly from the tool result and act on them
without any manual copy-pasting.

### Manual server start

```bash
agentmd mcp --root /path/to/project
```

The server reads JSON-RPC messages from stdin and writes responses to stdout,
one message per line. Errors and startup notices go to stderr.

---

## Claude Code

### AGENTS.md vs CLAUDE.md

Claude Code reads `CLAUDE.md` (not `AGENTS.md`) natively. To bridge this,
add an import line to your project's `CLAUDE.md`:

```markdown
@AGENTS.md

<!-- Claude-specific additions below -->
```

The `@AGENTS.md` import pulls in the full content of `AGENTS.md` at session
start. You can then add Claude-specific instructions beneath it.

The MCP server integration above is the recommended path — it gives the
agent structured, queryable access to context rather than a flat text dump.

### Session start hook

To inject resolved context at the start of every Claude Code session,
configure a `SessionStart` hook in `.claude/settings.json`:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "agentmd export . --json 2>/dev/null || true"
          }
        ]
      }
    ]
  }
}
```

`SessionStart` hook stdout is injected directly into Claude's context window.
The JSON output of `agentmd export` includes the resolved skills, rules,
conventions, and `prompt_snippets` for the project root.

> **Note**: `PreToolUse` hook stdout is **not** injected into Claude's
> context — use `SessionStart` or `UserPromptSubmit` for context injection.
> `PreToolUse` hooks communicate via exit codes and JSON responses on stdout
> (used for blocking or modifying tool calls, not for adding context).

---

## Cursor

### Native AGENTS.md

Cursor reads `AGENTS.md` from the project root in Agent mode without any
setup. This provides basic out-of-the-box compatibility, but note that
subdirectory `AGENTS.md` files and background agents (GitHub, Slack, Linear
integrations) may not load the file reliably. For structured, file-scoped
rules, use the `.cursor/rules/` approach below.

### .cursor/rules/ (recommended)

`.cursorrules` is deprecated as of Cursor 0.45 and will eventually be
removed. The current standard is `.cursor/rules/*.mdc` files with YAML
frontmatter. Each file defines one rule with explicit scope and trigger
behavior.

**MDC file format:**

```yaml
---
description: Short description shown in UI and used by the agent to decide relevance
globs: src/**/*.ts, src/**/*.tsx
alwaysApply: false
---

Rule body in Markdown...
```

**Four rule types** (determined by frontmatter values):

| Type | `alwaysApply` | `globs` | Trigger |
|------|--------------|---------|---------|
| Always | `true` | empty | Every chat session |
| Auto Attached | `false` | set | When a matching file is in context |
| Agent Requested | `false` | empty | AI reads `description` and decides |
| Manual | `false` | empty + no description | Only when @-mentioned |

**Generate `.cursor/rules/` from your agentmd context:**

```bash
agentmd export src/main.py | python3 scripts/generate-cursor-rules.py
```

`scripts/generate-cursor-rules.py`:

```python
import json, sys, pathlib, re

data = json.load(sys.stdin)
rules_dir = pathlib.Path(".cursor/rules")
rules_dir.mkdir(parents=True, exist_ok=True)

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

count = len(data.get("active_rules", [])) + (1 if data.get("agents_file") else 0)
print(f"Generated {count} rule file(s) in .cursor/rules/")
```

Add this to your `Makefile` or pre-commit hook to keep `.cursor/rules/`
in sync with your agentmd files.

---

## GitHub Copilot

### Copilot CLI (native AGENTS.md)

The `gh copilot` CLI natively reads `AGENTS.md` from the repository root,
the current working directory, and any directories listed in the
`COPILOT_CUSTOM_INSTRUCTIONS_DIRS` environment variable (comma-separated).
No additional setup is needed — agentmd's format is directly compatible.

### Copilot Chat (VS Code / Visual Studio / GitHub.com)

Copilot Chat reads `.github/copilot-instructions.md` for repository-level
instructions. Generate it from your agentmd context:

```bash
mkdir -p .github
agentmd export . --json | python3 scripts/generate-copilot-instructions.py \
  > .github/copilot-instructions.md
```

Where `scripts/generate-copilot-instructions.py` reads the JSON from stdin
and produces a Markdown document with the project's conventions and rules.

> **Code review limit**: Copilot's code review feature reads only the first
> **4,000 characters** of any instruction file; content beyond that is
> silently ignored. Keep the file concise or split instructions across
> path-scoped files (see below).

### Path-scoped instructions (cloud agent + code review)

For file-scoped rules analogous to agentmd's `RULE.md` `applies_to` field,
use `.github/instructions/*.instructions.md` files with an `applyTo`
frontmatter key (glob syntax). These are read by the Copilot cloud agent
and Copilot code review on GitHub.com:

```markdown
---
applyTo: "app/models/**/*.rb"
---

Use Rails conventions for all ActiveRecord models. Never bypass validations.
```

Generate one file per active agentmd rule:

```bash
mkdir -p .github/instructions
agentmd export . --json | python3 -c "
import json, sys, pathlib, re
data = json.load(sys.stdin)
for rule in data.get('active_rules', []):
    globs = ', '.join(rule.get('applies_to', ['**/*']))
    body = [
        '---',
        f'applyTo: \"{globs}\"',
        '---',
        '',
        f'## {rule[\"id\"]} [{rule[\"severity\"].upper()}]',
        '',
        rule.get('description', ''),
    ]
    if rule.get('rationale'):
        body.extend(['', f'**Rationale**: {rule[\"rationale\"]}'])
    fname = re.sub(r'[^a-z0-9-]', '-', rule['id'].lower()) + '.instructions.md'
    pathlib.Path('.github/instructions/' + fname).write_text('\n'.join(body))
    print(fname)
"
```

---

## Windsurf

### Native AGENTS.md

Windsurf natively reads `AGENTS.md` as part of its Rules engine:

- **Root-level `AGENTS.md`**: treated as `always_on` — included in every
  Cascade prompt with no frontmatter needed.
- **Subdirectory `AGENTS.md`**: auto-scoped as a glob rule for
  `<directory>/**` — applied only when Cascade reads or edits files in
  that directory.

This makes agentmd's file-scoped context model a direct fit for Windsurf.

### .windsurf/rules/ (modern rules)

Windsurf's `.windsurf/rules/*.md` files use YAML frontmatter with a
`trigger` field that maps naturally to agentmd rule scope:

```yaml
---
trigger: always_on
description: "Core coding standards"
---

Rule body in Markdown...
```

```yaml
---
trigger: glob
globs: "**/*.test.ts"
description: "Testing conventions"
---
```

| `trigger` value | Behaviour |
|-----------------|-----------|
| `always_on` | Included in every Cascade prompt |
| `glob` | Applied when matched files are in context |
| `model_decision` | Cascade decides contextually whether to apply |
| `manual` | Only applied when explicitly invoked via `/rule-name` |

Individual rule files are capped at **12,000 characters**.

The legacy `.windsurfrules` file (single flat file at project root) is
still supported for backward compatibility.

### .windsurf/workflows/ (skills analog)

`.windsurf/workflows/*.md` files are step-by-step procedure files invocable
via `/workflow-name` slash commands in Cascade — directly analogous to
agentmd's `SKILL.md` files. Generate them from your agentmd skills:

```bash
mkdir -p .windsurf/workflows
agentmd export . --json | python3 -c "
import json, sys, pathlib
data = json.load(sys.stdin)
for skill in data.get('active_skills', []):
    body = f'# {skill[\"id\"]}\n\n{skill[\"description\"]}\n\nTrigger: {skill[\"trigger\"]}\n'
    fname = skill['id'] + '.md'
    src = pathlib.Path(skill.get('path', ''))
    if src.exists():
        body += '\n' + src.read_text()
    pathlib.Path('.windsurf/workflows/' + fname).write_text(body)
    print(fname)
"
```

### MCP server

Add agentmd to `~/.codeium/windsurf/mcp_config.json` (Windsurf only
supports global MCP config, not project-level):

```json
{
  "mcpServers": {
    "agentmd": {
      "command": "agentmd",
      "args": ["mcp", "--root", "/absolute/path/to/your/project"]
    }
  }
}
```

---

## Pre-commit Hook

Add a `agentmd validate` step to your pre-commit config to catch schema
errors before they reach CI:

```yaml
# .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: agentmd-validate
        name: Validate agentmd files
        entry: agentmd validate
        language: python
        pass_filenames: false
        always_run: true
```

---

## CI / GitHub Actions

```yaml
# .github/workflows/agentmd.yml
name: agentmd validate

on: [push, pull_request]

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install agentmd
      - run: agentmd validate
```

---

## Export Format Reference

The JSON output of `agentmd export <file>` (and the MCP `agentmd_resolve`
tool) has this shape:

```json
{
  "agents_file": {
    "agentmd": "1.0",
    "type": "agents",
    "scope": "project",
    "name": "My Project",
    "stack": ["python", "fastapi"],
    "conventions": ["Use snake_case"],
    "skills": ["skills/scaffold.skill.md"],
    "rules": ["rules/no-raw-sql.rule.md"],
    "agent_instructions": "You are operating in..."
  },
  "active_skills": [
    {
      "agentmd": "1.0",
      "type": "skill",
      "id": "scaffold-endpoint",
      "version": "1.0",
      "description": "...",
      "trigger": "when asked to scaffold a new API endpoint",
      "inputs": [],
      "outputs": [],
      "tags": []
    }
  ],
  "active_rules": [
    {
      "agentmd": "1.0",
      "type": "rule",
      "id": "no-raw-sql",
      "severity": "error",
      "description": "...",
      "rationale": "...",
      "applies_to": ["**/*.py"],
      "exceptions": ["migrations/**"],
      "immutable": false
    }
  ],
  "source_files": [
    "/path/to/AGENTS.md",
    "/path/to/skills/scaffold-endpoint.skill.md"
  ],
  "merged_stack": ["python", "fastapi"],
  "merged_conventions": ["Use snake_case"],
  "prompt_snippets": [
    "You have access to the [scaffold-endpoint] procedure. To use it, follow the steps in [/path/to/skills/scaffold-endpoint.skill.md]. Trigger: when asked to scaffold a new API endpoint"
  ],
  "warnings": []
}
```

### Field notes

| Field | Description |
|---|---|
| `merged_stack` | Stack labels accumulated from all AGENTS.md files on the walk path (closest first). Useful in monorepos with multiple AGENTS.md files. |
| `merged_conventions` | Conventions accumulated from all AGENTS.md files on the walk path. |
| `prompt_snippets` | One ready-to-use instruction per active skill. Inject directly into the agent prompt or read via MCP. |
| `warnings` | Non-fatal issues from resolution (skipped broken files, duplicate skill references). Empty on a clean repo. |
