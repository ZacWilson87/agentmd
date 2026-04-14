---
agentmd: "1.0"
type: agents
scope: project
name: "agentmd"
stack:
  - python
  - typer
  - rich
  - pydantic
  - pyyaml
  - jinja2
conventions:
  - "Python 3.11+ type hints required on all public functions"
  - "Use snake_case for all Python identifiers"
  - "CLI output uses rich for formatting — no raw print() for user-facing output"
  - "All CLI commands are defined in agentmd/cli.py using typer"
  - "Pydantic v2 models live in agentmd/models.py — do not add validation logic elsewhere"
  - "Tests live in tests/ and use pytest with tmp_path fixtures for filesystem tests"
  - "Conservative error handling: if a file fails to parse during resolution, skip it silently"
  - "Do not add semantic analysis to the checker — pattern matching only"
skills:
  - skills/add-cli-command.skill.md
  - skills/add-file-type.skill.md
rules:
  - rules/no-print-statements.rule.md
  - rules/type-hints-required.rule.md
  - rules/tests-required.rule.md
agent_instructions: |
  You are implementing agentmd — the open standard for AI context in codebases.

  The spec is the source of truth. When in doubt, re-read docs/spec.md.

  Key invariants:
  1. The scope resolution algorithm in agentmd/resolver.py must match the spec exactly.
  2. Pydantic models in agentmd/models.py are the canonical schema — do not bypass them.
  3. The CLI in agentmd/cli.py must remain the single entry point for all commands.
  4. All three file types (AGENTS.md, SKILL.md, RULE.md) must parse identically
     whether encountered via resolve(), validate(), or list commands.
  5. agentmd must be usable as a library (import agentmd) not just as a CLI.

  Before adding a feature:
  - Check if a relevant SKILL.md exists in skills/
  - Check if any RULE.md in rules/ constrains the change

  File layout:
  - agentmd/cli.py       — typer app, all commands
  - agentmd/models.py    — pydantic models (AgentsFile, SkillFile, RuleFile)
  - agentmd/parser.py    — YAML frontmatter extraction + file parsing
  - agentmd/resolver.py  — scope resolution algorithm
  - agentmd/scaffolder.py — init + add commands (template rendering)
  - agentmd/exporter.py  — JSON serialisation for tool integration
  - agentmd/checker.py   — pattern-based rule violation detection
---

# agentmd

The open standard for AI context in codebases.

agentmd is both the standard it defines and the CLI tool that implements it.
This repository is a live showcase of the format — every skill and rule
described below is used in the development of agentmd itself.

## Architecture

agentmd is a pure Python CLI with no server, no database, and no network
requirements. All context lives in files in the repository.

```
CLI (typer) → Parser (PyYAML + Pydantic) → Resolver → Exporter
                                              ↕
                                          Scaffolder
```

## Key Decisions

- **File-based**: No central registry. Skills and rules live in files.
- **Scope by directory**: Context automatically narrows as you go deeper.
- **Conservative**: Broken files are skipped during resolution, not fatal.
- **Composable**: Multiple AGENTS.md files can coexist in a monorepo.
- **Machine + human**: Every file is both machine-parseable and human-readable.
