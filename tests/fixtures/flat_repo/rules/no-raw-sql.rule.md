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
  - "scripts/seed_*.py"
---

## Rule

Never write raw SQL strings. Use the `db.query()` ORM abstraction instead.

### Non-compliant

```python
cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
```

### Compliant

```python
user = db.query(User).filter(User.id == user_id).first()
```
