---
agentmd: "1.0"
type: rule
id: no-todo-comments
severity: warning
description: "TODO comments must not be committed"
rationale: "TODO comments indicate incomplete work; use the issue tracker instead"
applies_to:
  - "**/*"
exceptions:
  - "docs/**"
---

## Rule

Do not commit TODO comments. Create a GitHub issue instead.
