---
agentmd: "1.0"
type: rule
id: no-print-statements
severity: error
description: "No print() calls in agentmd source code"
rationale: "All user-facing output must go through rich Console for consistent formatting"
applies_to:
  - "agentmd/**/*.py"
exceptions:
  - "agentmd/templates/**"
---

## Rule

Never use `print()` in agentmd source files. Use the `rich` Console instead:

```python
from rich.console import Console
console = Console()
err_console = Console(stderr=True)

# For normal output:
console.print("...")

# For errors:
err_console.print("[red]Error:[/red] ...")
```

This ensures consistent formatting, colour support, and testability.
