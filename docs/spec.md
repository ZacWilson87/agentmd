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
severity: error           # error | warning | info
description: "All database queries must use the ORM layer"
rationale: "Prevents injection vulnerabilities and keeps query logic testable"
applies_to:
  - "**/*.py"
exceptions:
  - "migrations/**"
  - "scripts/seed_*.py"
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
| `severity` | `"error" \| "warning" \| "info"` | yes | — |
| `description` | string | yes | — |
| `rationale` | string | no | `""` |
| `applies_to` | list[glob] | no | `["**/*"]` |
| `exceptions` | list[glob] | no | `[]` |

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

5. Return ResolvedContext{agents_file, active_skills, active_rules, source_files}
```

### Key behaviours

- **Closest wins for AGENTS.md**: Only the first AGENTS.md found (deepest
  in the tree relative to the target) is used. Parent AGENTS.md files are
  ignored once one is found.
- **Skills and rules accumulate**: All `*.skill.md` and `*.rule.md` files
  in `skills/` and `rules/` directories along the entire walk path are
  collected. Closest-scope definitions win on ID collision.
- **Rule filtering**: Rules are filtered against the target file path using
  the `applies_to` glob patterns minus `exceptions`.
- **Conservative parsing**: Files that fail validation are silently skipped
  during resolution (they are reported as errors by `agentmd validate`).

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

`agentmd export <file>` produces a JSON object:

```json
{
  "agents_file": { ... } | null,
  "active_skills": [ { ... } ],
  "active_rules": [ { ... } ],
  "source_files": [ "..." ]
}
```

This format is designed for consumption by:
- Claude Code hooks (`PreToolUse`, `PostToolUse`)
- Cursor `.cursorrules` generation scripts
- CI rule-checking pipelines
- Any tool that needs structured AI context

---

## 6. Versioning

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
