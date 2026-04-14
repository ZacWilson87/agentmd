---
agentmd: "1.0"
type: rule
id: no-console-log
severity: error
description: "No console.log() calls in committed code"
rationale: "Debug logging should not reach production"
applies_to:
  - "**/*.ts"
  - "**/*.tsx"
exceptions:
  - "**/*.test.ts"
  - "**/*.test.tsx"
---

## Rule

Remove all `console.log()` calls before committing.
Use a proper logger or remove debug output.
