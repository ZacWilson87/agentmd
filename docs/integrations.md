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

2. Add agentmd to your Claude Code MCP configuration in
   `.claude/settings.json`:
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

Claude Code supports hooks that run shell commands in response to tool events.
Use `agentmd export` in a `PreToolUse` hook to inject context before every
file operation.

### Setup

1. Install agentmd in your project:
   ```bash
   pip install agentmd
   # or with uv:
   uv add agentmd
   ```

2. Add a `AGENTS.md` at your project root:
   ```bash
   agentmd init
   ```

3. Configure a Claude Code hook in `.claude/settings.json`:
   ```json
   {
     "hooks": {
       "PreToolUse": [
         {
           "matcher": ".*",
           "hooks": [
             {
               "type": "command",
               "command": "agentmd export \"$CLAUDE_TOOL_INPUT_PATH\" 2>/dev/null || true"
             }
           ]
         }
       ]
     }
   }
   ```

4. Claude Code will receive the resolved context JSON on stdout before
   each tool use, giving it structured awareness of your project's skills,
   rules, and conventions.

### Advanced: File-specific context

You can also query context in a session start hook to prime Claude's
understanding of the whole project:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "agentmd resolve . --json"
          }
        ]
      }
    ]
  }
}
```

---

## Cursor

Cursor reads `.cursorrules` for project-level instructions.
Generate it from your agentmd context:

```bash
agentmd export src/main.py | python3 -c "
import json, sys
ctx = json.load(sys.stdin)
rules = []
if ctx['agents_file']:
    a = ctx['agents_file']
    rules.append(f'# {a[\"name\"]}')
    rules.append('')
    if a['agent_instructions']:
        rules.append(a['agent_instructions'])
    if a['conventions']:
        rules.append('## Conventions')
        for c in a['conventions']:
            rules.append(f'- {c}')
    if a['stack']:
        rules.append(f'## Stack: {', '.join(a['stack'])}')
for rule in ctx['active_rules']:
    rules.append(f'## Rule [{rule['severity']}]: {rule['id']}')
    rules.append(rule['description'])
print('\n'.join(rules))
" > .cursorrules
```

Add this to your `Makefile` or pre-commit hook to keep `.cursorrules`
in sync with your agentmd files.

---

## GitHub Copilot

Copilot uses `.github/copilot-instructions.md` for repository-level
instructions.

Generate it from your agentmd context:

```bash
mkdir -p .github
agentmd export . --json | python3 scripts/generate-copilot-instructions.py \
  > .github/copilot-instructions.md
```

Where `scripts/generate-copilot-instructions.py` reads the JSON from stdin
and produces a Markdown document with the project's conventions and rules.

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
