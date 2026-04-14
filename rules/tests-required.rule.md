---
agentmd: "1.0"
type: rule
id: tests-required
severity: warning
description: "New public functions must have corresponding tests"
rationale: "agentmd is a developer tool; untested behaviour erodes trust in the standard"
applies_to:
  - "agentmd/**/*.py"
exceptions:
  - "agentmd/cli.py"
  - "agentmd/templates/**"
---

## Rule

Every new public function added to the `agentmd` package must have at least
one test in the corresponding `tests/test_<module>.py` file.

The test must cover:
1. The happy path (valid input, expected output)
2. At least one error case (invalid input, missing file, etc.)

### Convention

Test files mirror the module structure:
- `agentmd/parser.py` → `tests/test_parser.py`
- `agentmd/resolver.py` → `tests/test_resolver.py`
- `agentmd/models.py` → `tests/test_models.py`
