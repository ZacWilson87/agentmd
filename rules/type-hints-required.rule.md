---
agentmd: "1.0"
type: rule
id: type-hints-required
severity: warning
description: "All public functions must have type annotations"
rationale: "Type hints improve IDE support, catch bugs early, and serve as inline documentation"
applies_to:
  - "agentmd/**/*.py"
exceptions:
  - "agentmd/templates/**"
  - "tests/**"
---

## Rule

All public functions (not prefixed with `_`) must have:
1. Parameter type annotations
2. Return type annotation

### Non-compliant

```python
def resolve(target):
    ...
```

### Compliant

```python
def resolve(target: Path) -> ResolvedContext:
    ...
```

Private helpers (prefixed `_`) are exempt but encouraged to have types too.
