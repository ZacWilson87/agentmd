# agentmd

> The open standard for AI context in codebases.

agentmd defines three file types — `AGENTS.md`, `SKILL.md`, and `RULE.md`
— that give AI coding assistants structured, file-scoped context about
your project: what it is, what it can do, and what rules it must follow.

Think `.editorconfig`, but for AI.

---

## Why agentmd?

Every AI coding assistant (Claude Code, Cursor, Copilot) faces the same
problem: they have no structured way to understand the intent, constraints,
and skill set of the codebase they're operating in. Developers compensate
with ad-hoc instruction blocks scattered across README files, editor comments,
and prompt snippets.

agentmd standardises this as a portable, composable, file-scoped context system.

---

## The Three File Types

| File | Purpose |
|------|---------|
| `AGENTS.md` | Project-level operating charter — what the project is, its stack, conventions, and agent instructions |
| `*.skill.md` | Reusable AI capability — a named, callable procedure for a recurring task |
| `*.rule.md` | Scoped constraint — a rule that applies to specific files or directories |

All three use YAML frontmatter + Markdown body. Machine-readable metadata,
human-readable narrative, in one file.

---

## Quick Start

```bash
pip install agentmd
# or: uv add agentmd

# Bootstrap your project
cd my-project
agentmd init

# Validate all agentmd files
agentmd validate

# See resolved context for a file
agentmd resolve src/api/views.py

# List all skills and rules
agentmd list skills
agentmd list rules

# Scaffold a new skill
agentmd add skill scaffold-endpoint

# Export context as JSON (for tool integration)
agentmd export src/api/views.py
```

---

## AGENTS.md Example

```yaml
---
agentmd: "1.0"
type: agents
scope: project
name: "My Project"
stack:
  - python
  - fastapi
  - react
  - postgresql
conventions:
  - "Use snake_case for all Python identifiers"
  - "All API responses use camelCase JSON"
  - "No print() statements — use structlog"
skills:
  - skills/scaffold-endpoint.skill.md
rules:
  - rules/no-raw-sql.rule.md
agent_instructions: |
  You are operating in a production FastAPI + React monorepo.
  Always check the relevant SKILL.md before implementing a feature.
  Never modify files in /generated — they are auto-produced.
---

# My Project

Narrative description for humans...
```

---

## SKILL.md Example

```yaml
---
agentmd: "1.0"
type: skill
id: scaffold-react-component
version: "1.2"
description: "Scaffold a new React component with tests and Storybook story"
trigger: "when asked to create a new React component"
inputs:
  - name: component_name
    type: string
    required: true
outputs:
  - "src/components/{component_name}/{component_name}.tsx"
tags: [frontend, react, scaffold]
---

## Steps

1. Create the component file...
```

---

## RULE.md Example

```yaml
---
agentmd: "1.0"
type: rule
id: no-raw-sql
severity: error
description: "All database queries must use the ORM layer"
rationale: "Prevents injection vulnerabilities"
applies_to:
  - "**/*.py"
exceptions:
  - "migrations/**"
---

## Rule

Never write raw SQL strings. Use the ORM abstraction...
```

---

## Scope Resolution

agentmd uses directory-based scope resolution. When you run
`agentmd resolve src/api/views.py`, it walks up the directory tree and:

1. Finds the nearest `AGENTS.md` (closest wins — useful for monorepos)
2. Accumulates all `*.skill.md` files from `skills/` directories along the path
3. Accumulates all `*.rule.md` files from `rules/` directories along the path
4. Filters rules by their `applies_to` glob patterns

This means a monorepo can have:
- A root `AGENTS.md` for the whole project
- A `backend/AGENTS.md` that overrides it for the backend package
- Rules in `backend/rules/` that only apply to Python files
- Frontend skills in `frontend/skills/` scoped to the React code

---

## CLI Reference

```
agentmd init [PATH]             Bootstrap AGENTS.md, /skills, /rules
agentmd validate [PATH]         Validate all agentmd files
agentmd resolve <FILE>          Show resolved context for a file
agentmd list skills [PATH]      List all skills (table)
agentmd list rules [PATH]       List all rules (table)
agentmd add skill <ID> [PATH]   Scaffold a new SKILL.md
agentmd add rule <ID> [PATH]    Scaffold a new RULE.md
agentmd export <FILE>           Export resolved context as JSON
agentmd check <FILE>            Check rule violations for a file
```

---

## Tool Integration

agentmd's JSON export format is designed for tool integration:

**Claude Code** — use `agentmd export` in a `PreToolUse` hook to inject
structured context before each operation. See [docs/integrations.md](docs/integrations.md).

**Cursor** — generate `.cursorrules` from `agentmd export` output.

**Copilot** — populate `.github/copilot-instructions.md` from your
agentmd context.

**CI** — run `agentmd validate` as a pre-commit hook or GitHub Actions step.

---

## Specification

The full formal specification is in [docs/spec.md](docs/spec.md).

---

## License

MIT — see [LICENSE](LICENSE).
