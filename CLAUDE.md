# agentmd — AI Operating Charter

You are the sole implementer of agentmd. Work autonomously through the phases below.
Commit after each phase. The spec is the source of truth.
Make conservative choices on ambiguities and document them inline.

---

## Philosophy

Every AI coding assistant (Claude Code, Cursor, Copilot) struggles with the same
problem: they have no structured way to understand the intent, constraints, and skill
set of the codebase they're operating in. Developers compensate with ad-hoc instructions
in random places.

agentmd is the standard that fixes this. It defines a portable, composable, file-scoped
context system using three file types:

- **AGENTS.md** — project-level operating charter for AI agents
- **SKILL.md** — reusable, callable AI capability definition
- **RULE.md** — scoped constraint or convention file

The CLI (`agentmd`) bootstraps, validates, and resolves this context so any AI tool
can consume it consistently.

Think: `.editorconfig` for AI context. Simple, file-based, no server.

---

## Decisions (do not relitigate)

| Decision | Choice |
|----------|--------|
| Language | Python 3.11+ |
| CLI framework | typer with rich for output |
| Schema validation | pydantic v2 |
| YAML parsing | PyYAML |
| Config resolution | file-system traversal (walk up from CWD) |
| Output format | JSON (machine-readable) + rich tables (human) |
| Packaging | pyproject.toml with uv, published to PyPI as `agentmd` |
| Template engine | Jinja2 |
| License | MIT |

---

## Repository Structure

```
agentmd/
├── agentmd/
│   ├── __init__.py
│   ├── cli.py               # typer app — all commands
│   ├── models.py            # pydantic models for all 3 file types
│   ├── parser.py            # YAML frontmatter extraction + validation
│   ├── resolver.py          # scope resolution algorithm
│   ├── scaffolder.py        # init + add commands (template generation)
│   ├── checker.py           # pattern-based rule violation detection
│   ├── exporter.py          # JSON export for tool integration
│   └── templates/
│       ├── AGENTS.md.jinja
│       ├── skill.md.jinja
│       └── rule.md.jinja
├── tests/
│   ├── fixtures/            # sample repo directory trees for testing
│   ├── test_parser.py
│   ├── test_resolver.py
│   ├── test_cli.py
│   └── test_models.py
├── docs/
│   ├── spec.md              # The formal agentmd 1.0 specification
│   ├── integrations.md      # Claude Code, Cursor, Copilot integration guides
│   └── examples/            # annotated example repos
├── skills/                  # agentmd's own skills (meta-showcase)
├── rules/                   # agentmd's own rules (meta-showcase)
├── pyproject.toml
├── AGENTS.md                # agentmd describes itself (showcase of the format)
└── README.md
```

---

## Implementation Phases

### Phase 0 — Skeleton ✓
- pyproject.toml with typer, rich, pydantic, PyYAML, jinja2
- Empty module structure
- `agentmd --help` returns usage

### Phase 1 — Models + Parser ✓
- All three Pydantic models (AgentsFile, SkillFile, RuleFile)
- YAML frontmatter extractor (regex split on --- blocks)
- Validation error messages with file path + field name
- Tests: valid files parse correctly, invalid files raise with clear messages

### Phase 2 — Resolver ✓
- Directory walk algorithm (walk up from target file to filesystem root)
- ResolvedContext assembly
- Glob filtering for rules (applies_to / exceptions)
- Tests: flat repo, nested repo, missing AGENTS.md, conflicting scopes

### Phase 3 — CLI Core ✓
- `agentmd init` — creates AGENTS.md + /skills + /rules from templates
- `agentmd validate` — walks repo, validates all, rich table output
- `agentmd resolve <file>` — pretty-prints resolved context
- `agentmd list skills` / `agentmd list rules` — rich tables

### Phase 4 — Scaffolding ✓
- Jinja2 template rendering for AGENTS.md, SKILL.md, RULE.md
- `agentmd add skill <id>` and `agentmd add rule <id>`
- Auto-register in nearest AGENTS.md's skills/rules list

### Phase 5 — Export + Check ✓
- `agentmd export` — JSON output consumable by Claude Code hooks
- `agentmd check` — rule violation reporting (pattern matching, not semantic analysis)

### Phase 6 — Docs + Meta ✓
- `docs/spec.md` — formal 1.0 specification
- `docs/integrations.md` — how to wire agentmd into Claude Code, Cursor, Copilot
- The repo's own `AGENTS.md` is a showcase of the format itself
- `README.md` with philosophy, quickstart, spec link, integration guide links

---

## Key Invariants

1. The scope resolution algorithm in `agentmd/resolver.py` must match `docs/spec.md`.
2. Pydantic models in `agentmd/models.py` are the canonical schema.
3. All CLI commands are in `agentmd/cli.py` using typer.
4. Conservative error handling: broken files are skipped during resolution, reported by validate.
5. No print() in source — use rich Console.
6. Type hints required on all public functions.
7. `agentmd` must be usable as a library, not just a CLI.

---

## Conservative Choices (Documented)

- **Checker is pattern-only**: `agentmd check` uses regex patterns for known rule IDs.
  It does not attempt semantic analysis. Unknown rule IDs are silently skipped.
  Rationale: semantic analysis is language-specific and out of scope for v1.0.

- **AGENTS.md closest-wins**: When walking up the tree, the first AGENTS.md found is used.
  Parent AGENTS.md files are ignored once one is found. Rationale: the spec states
  "closest wins for project scope."

- **Broken files skipped during resolution**: If a file fails to parse during `resolve()`,
  it is silently skipped. It will be reported as an error by `agentmd validate`.
  Rationale: resolution should never fail due to a broken file in a distant directory.

- **Skills accumulate, rules accumulate**: All skills and rules along the walk path are
  collected. ID collision is resolved by closest-scope-first (first occurrence wins).
