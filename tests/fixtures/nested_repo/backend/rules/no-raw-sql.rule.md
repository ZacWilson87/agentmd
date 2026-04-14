---
agentmd: "1.0"
type: rule
id: no-raw-sql
severity: error
description: "All database queries must use the ORM layer"
rationale: "Prevents injection vulnerabilities and keeps query logic testable"
applies_to:
  - "**/*.py"
exceptions:
  - "migrations/**"
---

## Rule

Never write raw SQL strings. Use the ORM abstraction.
