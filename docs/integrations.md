# agentmd Integrations

How to wire agentmd into your AI coding tools.

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

The JSON output of `agentmd export <file>` has this shape:

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
      "trigger": "...",
      "inputs": [...],
      "outputs": [...],
      "tags": [...]
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
      "exceptions": ["migrations/**"]
    }
  ],
  "source_files": [
    "/path/to/AGENTS.md",
    "/path/to/skills/scaffold-endpoint.skill.md"
  ]
}
```
