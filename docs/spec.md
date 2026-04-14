# agentmd 1.0 Specification

> The formal specification for the agentmd AI context standard.

## Abstract

agentmd is a file-based standard for providing structured, scoped context
to AI coding assistants. It defines three file types — `AGENTS.md`,
`SKILL.md`, and `RULE.md` — and a deterministic scope resolution algorithm
for assembling that context for any file in a codebase.

---

## 1. Motivation

AI coding assistants operate without structured knowledge of:

- What a project does and how it is organised
- What conventions and constraints apply to specific parts of the codebase
- What reusable AI capabilities (skills) exist for common tasks

Developers compensate with ad-hoc instruction blocks scattered across
README files, editor config comments, and prompt snippets. agentmd
standardises this as a portable, composable, file-scoped context system.

---

## 2. File Types

### 2.1 AGENTS.md

**Purpose**: Defines the AI agent's operating context for a directory scope.

**Naming**: Must be named exactly `AGENTS.md` (case-sensitive).

**Location**: Typically at project root, but may appear in any directory
to provide package or module-level context.

**Structure**: YAML frontmatter block followed by free-form Markdown body.

```yaml
---
agentmd: "1.0"
type: agents
scope: project           # project | package | module
name: "My Project"
stack:
  - python
  - fastapi
conventions:
  - "Use snake_case for all Python identifiers"
skills:                  # relative paths to SKILL.md files
  - skills/scaffold-component.skill.md
rules:                   # relative paths to RULE.md files
  - rules/no-raw-sql.rule.md
agent_instructions: |
  Narrative instructions for the AI agent operating in this scope.
---

# My Project

Human-readable description...
```

**Schema** (`AgentsFile`):

| Field | Type | Required | Default |
|-------|------|----------|---------|
| `agentmd` | `"1.0"` | yes | — |
| `type` | `"agents"` | yes | — |
| `scope` | `"project" \| "package" \| "module"` | no | `"project"` |
| `name` | string | yes | — |
| `stack` | list[string] | no | `[]` |
| `conventions` | list[string] | no | `[]` |
| `skills` | list[string] | no | `[]` |
| `rules` | list[string] | no | `[]` |
| `agent_instructions` | string | no | `""` |

---

### 2.2 SKILL.md

**Purpose**: Defines a reusable AI capability — a named, callable procedure
an agent can follow to accomplish a recurring task.

**Naming**: `<id>.skill.md` where `<id>` is a kebab-case identifier.

**Location**: Anywhere in the repo. Skills are scoped to the directory
subtree they live in (and below). Convention: place in a `skills/`
subdirectory.

**Structure**: YAML frontmatter + Markdown body describing the steps.

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
  - name: variant
    type: enum
    values: [functional, compound, page]
    default: functional
outputs:
  - "src/components/{component_name}/{component_name}.tsx"
tags: [frontend, react, scaffold]
---

## Steps

1. Create the component...
```

**Schema** (`SkillFile`):

| Field | Type | Required |
|-------|------|----------|
| `agentmd` | `"1.0"` | yes |
| `type` | `"skill"` | yes |
| `id` | kebab-case string | yes |
| `version` | string | yes |
| `description` | string | yes |
| `trigger` | string | yes |
| `inputs` | list[SkillInput] | no |
| `outputs` | list[string] | no |
| `tags` | list[string] | no |

**SkillInput schema**:

| Field | Type | Required |
|-------|------|----------|
| `name` | string | yes |
| `type` | `"string" \| "enum" \| "boolean" \| "integer"` | yes |
| `required` | boolean | no (default: `true`) |
| `values` | list[string] | no (for `enum` type) |
| `default` | string | no |

---

### 2.3 RULE.md

**Purpose**: Defines a scoped constraint or convention that applies to
files matching specified glob patterns.

**Naming**: `<id>.rule.md` where `<id>` is a kebab-case identifier.

**Location**: Anywhere in the repo, scoped to its directory subtree.
Convention: place in a `rules/` subdirectory.

```yaml
---
agentmd: "1.0"
type: rule
id: no-raw-sql
severity: error           # critical | error | warning | info
description: "All database queries must use the ORM layer"
rationale: "Prevents injection vulnerabilities and keeps query logic testable"
applies_to:
  - "**/*.py"
exceptions:
  - "migrations/**"
  - "scripts/seed_*.py"
# Optional linter integration
linter_command: "sqlfluff lint --dialect ansi {file}"
linter_regex: "execute\\s*\\(\\s*[\"']"
---

## Rule

Never write raw SQL strings...
```

**Schema** (`RuleFile`):

| Field | Type | Required | Default |
|-------|------|----------|---------|
| `agentmd` | `"1.0"` | yes | — |
| `type` | `"rule"` | yes | — |
| `id` | kebab-case string | yes | — |
| `severity` | `"critical" \| "error" \| "warning" \| "info"` | yes | — |
| `description` | string | yes | — |
| `rationale` | string | no | `""` |
| `applies_to` | list[glob] | no | `["**/*"]` |
| `exceptions` | list[glob] | no | `[]` |
| `immutable` | boolean | no | `false` |
| `linter_command` | string | no | `null` |
| `linter_regex` | string | no | `null` |

**`immutable`**: When `true`, this rule cannot be displaced by a closer-scope
rule with the same `id`. Useful for security or compliance rules that must
apply project-wide regardless of subdirectory overrides. Immutable rules
take priority over non-immutable rules of the same `id` at any scope depth.

**`severity: critical`**: The highest severity level. Critical violations
are treated as hard blockers by `agentmd commit` — the commit is refused
until they are resolved. They also cause `agentmd audit` to fail.

**`linter_command`**: Optional shell command executed per-file during
`agentmd check` and `agentmd commit`. Use `{file}` as a placeholder for
the target file path (e.g. `"mypy {file} --no-error-summary"`). If `{file}`
is absent the path is appended as the last argument. Exit code 0 means clean;
non-zero means violations. stdout/stderr lines become violation messages.

**`linter_regex`**: Optional regex pattern searched line-by-line in the file
content. Any matching line is reported as a violation with its line number.
Runs in addition to any built-in checker for the same rule ID.

---

## 3. Scope Resolution Algorithm

When a tool queries context for a given file path, the resolution
algorithm produces a `ResolvedContext`:

```
resolve(target_file_path) -> ResolvedContext
```

### Algorithm

```
1. start_dir = target_file_path.parent
2. current = start_dir
3. agents_found = False

LOOP:
   a. If AGENTS.md exists at current/ and not agents_found:
      - Parse and store as agents_file
      - Load referenced skills (agents.skills paths)
      - Load referenced rules (agents.rules paths)
      - Set agents_found = True

   b. Collect all *.skill.md from current/skills/ (accumulate, closest first)
      - Skip any skill whose id was already collected

   c. Collect all *.rule.md from current/rules/ (accumulate, closest first)
      - Skip any rule whose id was already collected

   d. current = current.parent
   e. If current == current.parent: STOP (filesystem root reached)

4. Filter active_rules: keep only those matching applies_to against target
   (after excluding exceptions)

5. Generate prompt_snippets: one instruction per active_skill in the format:
   "You have access to the [id] procedure. To use it, follow the steps in
   [path]. Trigger: [trigger]."

6. Return ResolvedContext{
     agents_file, active_skills, active_rules,
     source_files, merged_stack, merged_conventions,
     skill_paths, prompt_snippets, warnings
   }
```

### Key behaviours

- **Closest wins for AGENTS.md**: Only the first AGENTS.md found (deepest
  in the tree relative to the target) is used. Parent AGENTS.md files are
  ignored once one is found. Stack and conventions, however, accumulate
  additively from all AGENTS.md files encountered (useful for monorepos).
- **Skills and rules accumulate**: All `*.skill.md` and `*.rule.md` files
  in `skills/` and `rules/` directories along the entire walk path are
  collected. Closest-scope definitions win on ID collision.
- **Immutable rule priority**: A rule marked `immutable: true` takes
  precedence over any non-immutable rule with the same `id`, regardless
  of scope depth.
- **Rule filtering**: Rules are filtered against the target file path using
  the `applies_to` glob patterns minus `exceptions`.
- **Conservative parsing**: Files that fail validation are silently skipped
  during resolution (they are reported as errors by `agentmd validate`).
  Skipped files are recorded in `warnings` on the `ResolvedContext`.
- **Duplicate skill reference guard**: If the same skill file path appears
  more than once in an AGENTS.md `skills` list, the duplicate is skipped and
  a warning is added to `ResolvedContext.warnings`. Resolution never fails
  due to duplicate references.
- **Prompt snippets**: After collecting all active skills, the resolver
  generates one prompt snippet per skill for direct agent consumption.

---

## 4. Validation

All three file types are validated against their Pydantic models.
The `agentmd validate` command walks the repo and reports schema errors
with file path and field references.

Rules for valid frontmatter:
1. File must begin with a `---` delimited YAML block.
2. YAML must parse as a dict (mapping).
3. `agentmd` field must equal `"1.0"`.
4. `type` field must match the filename convention.
5. All required fields must be present.
6. Enum fields (`scope`, `severity`, `type`) must use allowed values.
7. `id` fields must be kebab-case (`[a-z0-9]+(-[a-z0-9]+)*`).

---

## 5. Export Format

`agentmd export <file>` (and the MCP `agentmd_resolve` tool) produce a JSON
object:

```json
{
  "agents_file": { ... } | null,
  "active_skills": [ { ... } ],
  "active_rules": [ { ... } ],
  "source_files": [ "..." ],
  "merged_stack": [ "..." ],
  "merged_conventions": [ "..." ],
  "prompt_snippets": [ "..." ],
  "warnings": [ "..." ]
}
```

| Field | Description |
|---|---|
| `agents_file` | The nearest AGENTS.md model, or `null` if none found |
| `active_skills` | All `SkillFile` records in scope (closest-scope first) |
| `active_rules` | All `RuleFile` records that apply to the target file |
| `source_files` | Ordered list of every agentmd file loaded during resolution |
| `merged_stack` | Stack labels from all AGENTS.md files on the path (additive) |
| `merged_conventions` | Conventions from all AGENTS.md files (additive) |
| `prompt_snippets` | One ready-to-use agent instruction per active skill |
| `warnings` | Non-fatal issues collected during resolution (empty on clean repos) |

This format is designed for consumption by:
- The agentmd MCP server (`agentmd mcp`) — exposes all fields as tool output
- Claude Code hooks (`PreToolUse`, `PostToolUse`)
- Cursor `.cursorrules` generation scripts
- CI rule-checking pipelines
- Any tool that needs structured AI context

---

## 6. Commit Gate

`agentmd commit` is the bridge between the Resolver and a VCS commit workflow.
It enforces rules against staged changes before a commit is created.

### Algorithm

```
commit_gate(root) → CommitAnalysis

1. staged = git diff --cached --name-only (added/modified files only)
2. For each file in staged:
   a. ctx = resolve(file)
   b. violations = check_file(file, ctx)
      — runs built-in checker (if any) + linter_regex + linter_command
3. Classify violations by severity
4. If any critical violations: exit 1 (blocked)
5. Infer suggested_scope from ctx skill tags / AGENTS.md scope / directory
6. Infer suggested_type from file patterns (feat | fix | docs | test | chore)
7. Return CommitAnalysis { staged_files, violations, suggested_scope, suggested_type }
```

### Scope inference

The suggested commit scope is derived in priority order:

1. **Skill tags** — the most-frequent tag across all resolved skills for
   staged files (e.g. tag `"db"` → scope `db`).
2. **Package/module AGENTS.md** — when staged files resolve to a package-scope
   `AGENTS.md`, the directory name is used as scope.
3. **Common subdirectory** — the top-level subdirectory shared by all staged
   files.
4. **None** — if staged files span unrelated areas, no scope is suggested.

### Type inference

| Commit type | Condition |
|-------------|-----------|
| `docs` | All staged files are `.md` or inside `docs/` |
| `test` | All staged files are inside `tests/` or match `test_*` / `*.test.*` |
| `chore` | All staged files are config/meta files (pyproject.toml, .gitignore…) |
| `fix` | All staged files are modifications of existing files (no new files) |
| `feat` | Default |

### Pre-commit hook usage

Wire `agentmd commit --check-only` into git hooks or pre-commit:

```yaml
# .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: agentmd-commit-gate
        name: agentmd commit gate
        entry: agentmd commit --check-only
        language: python
        pass_filenames: false
        always_run: true
```

---

## 7. Versioning

The spec version is indicated by the `agentmd` field in every file.
Current version: `"1.0"`.

Future versions will increment this value. The CLI enforces spec version
compatibility and will report an error for unknown versions.

---

## 7. Design Decisions

**Why Markdown with YAML frontmatter?**
Markdown files are universally readable, diffable, and supported by every
editor. Frontmatter is a well-established convention (Hugo, Jekyll, etc.)
that keeps machine-readable data co-located with human-readable narrative.

**Why file-system traversal instead of a config file?**
File-system scoping is self-describing and requires no registry or central
configuration. It composes naturally: adding a skill in a subdirectory
automatically scopes it to that subtree without modifying any other file.

**Why closest-wins for AGENTS.md?**
A package-level AGENTS.md is more specific and relevant than the project-level
one. The closest file provides the most accurate context for the target.

**Why accumulate for skills and rules?**
Skills and rules are additive. A rule defined at project scope should still
apply in subdirectories unless overridden. Accumulation with ID-based
deduplication (closest wins on collision) achieves this naturally.
