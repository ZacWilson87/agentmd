"""Tests for the enhanced checker (AST-based + multi-file scan)."""

import pytest
from pathlib import Path

from agentmd.checker import (
    ViolationDetail,
    check_file,
    scan_repo,
    _ast_check_no_print_statements,
    _ast_check_no_raw_sql,
    _ast_check_type_hints_required,
)
from agentmd.resolver import resolve, ResolvedContext


AGENTS = """\
---
agentmd: "1.0"
type: agents
name: "Test"
---
"""

RULE_NO_PRINT = """\
---
agentmd: "1.0"
type: rule
id: no-print-statements
severity: error
description: "No print() calls"
applies_to:
  - "**/*.py"
---
"""

RULE_NO_SQL = """\
---
agentmd: "1.0"
type: rule
id: no-raw-sql
severity: error
description: "No raw SQL"
applies_to:
  - "**/*.py"
---
"""

RULE_TYPE_HINTS = """\
---
agentmd: "1.0"
type: rule
id: type-hints-required
severity: warning
description: "Type hints required"
applies_to:
  - "**/*.py"
---
"""

RULE_NO_CONSOLE_LOG = """\
---
agentmd: "1.0"
type: rule
id: no-console-log
severity: error
description: "No console.log"
applies_to:
  - "**/*.ts"
---
"""


def _setup(tmp_path: Path, rules: list[str]) -> Path:
    (tmp_path / "AGENTS.md").write_text(AGENTS)
    (tmp_path / "rules").mkdir()
    rule_map = {
        "no-print-statements": RULE_NO_PRINT,
        "no-raw-sql": RULE_NO_SQL,
        "type-hints-required": RULE_TYPE_HINTS,
        "no-console-log": RULE_NO_CONSOLE_LOG,
    }
    for rule_id in rules:
        (tmp_path / "rules" / f"{rule_id}.rule.md").write_text(rule_map[rule_id])
    return tmp_path


class TestASTNoprint:
    def test_detects_print(self):
        code = "print('hello')\nx = 1\n"
        violations = _ast_check_no_print_statements(code)
        assert len(violations) == 1
        assert violations[0].line == 1

    def test_multiple_prints(self):
        code = "print('a')\nx = 1\nprint('b')\n"
        violations = _ast_check_no_print_statements(code)
        assert len(violations) == 2

    def test_no_violation(self):
        code = "logger.info('hello')\nx = 1\n"
        violations = _ast_check_no_print_statements(code)
        assert violations == []

    def test_print_in_expression_ok(self):
        # print as part of a larger expression (not a standalone call)
        code = "result = [print(x) for x in items]\n"
        # This is not an ast.Expr wrapping a Call — it's inside a list comp
        violations = _ast_check_no_print_statements(code)
        assert violations == []

    def test_invalid_syntax_returns_empty(self):
        violations = _ast_check_no_print_statements("def (broken syntax")
        assert violations == []


class TestASTNoRawSQL:
    def test_detects_execute_with_string(self):
        code = 'cursor.execute("SELECT * FROM users")\n'
        violations = _ast_check_no_raw_sql(code)
        assert len(violations) == 1
        assert violations[0].line == 1

    def test_detects_different_sql_keywords(self):
        code = 'db.execute("INSERT INTO t VALUES (1)")\n'
        violations = _ast_check_no_raw_sql(code)
        assert len(violations) == 1

    def test_no_violation_orm(self):
        code = "db.query(User).filter(User.id == uid).first()\n"
        violations = _ast_check_no_raw_sql(code)
        assert violations == []

    def test_no_violation_parameterized(self):
        # Variable (not a string literal) passed to execute
        code = "cursor.execute(query, params)\n"
        violations = _ast_check_no_raw_sql(code)
        assert violations == []


class TestASTTypeHints:
    def test_detects_missing_return_type(self):
        code = "def my_func(x: int):\n    return x + 1\n"
        violations = _ast_check_type_hints_required(code)
        assert any("my_func" in v.message and "return type" in v.message for v in violations)

    def test_detects_missing_param_type(self):
        code = "def my_func(x) -> int:\n    return x + 1\n"
        violations = _ast_check_type_hints_required(code)
        assert any("Parameter 'x'" in v.message for v in violations)

    def test_no_violation_fully_annotated(self):
        code = "def my_func(x: int) -> int:\n    return x + 1\n"
        violations = _ast_check_type_hints_required(code)
        assert violations == []

    def test_skips_private_functions(self):
        code = "def _private(x):\n    return x\n"
        violations = _ast_check_type_hints_required(code)
        assert violations == []

    def test_skips_dunder(self):
        code = "def __init__(self, x):\n    self.x = x\n"
        violations = _ast_check_type_hints_required(code)
        assert violations == []


class TestCheckFile:
    def test_violations_returned_with_lines(self, tmp_path):
        root = _setup(tmp_path, ["no-print-statements"])
        py_file = tmp_path / "app.py"
        py_file.write_text("x = 1\nprint('debug')\ny = 2\n")
        ctx = resolve(py_file)
        violations = check_file(py_file, ctx)
        assert "no-print-statements" in violations
        assert violations["no-print-statements"][0].line == 2

    def test_no_violations_clean_file(self, tmp_path):
        root = _setup(tmp_path, ["no-print-statements"])
        py_file = tmp_path / "app.py"
        py_file.write_text("import logging\nlogger = logging.getLogger(__name__)\n")
        ctx = resolve(py_file)
        violations = check_file(py_file, ctx)
        assert violations == {}

    def test_unknown_rule_skipped(self, tmp_path):
        (tmp_path / "AGENTS.md").write_text(AGENTS)
        (tmp_path / "rules").mkdir()
        (tmp_path / "rules" / "custom-rule.rule.md").write_text(
            "---\nagentmd: '1.0'\ntype: rule\nid: custom-rule\nseverity: error\n"
            "description: 'custom'\napplies_to:\n  - '**/*.py'\n---\n"
        )
        py_file = tmp_path / "app.py"
        py_file.write_text("x = 1\n")
        ctx = resolve(py_file)
        violations = check_file(py_file, ctx)
        # No checker for unknown rule — silently skipped
        assert violations == {}

    def test_js_file_uses_regex_checker(self, tmp_path):
        root = _setup(tmp_path, ["no-console-log"])
        ts_file = tmp_path / "app.ts"
        ts_file.write_text("const x = 1;\nconsole.log('debug');\n")
        ctx = resolve(ts_file)
        violations = check_file(ts_file, ctx)
        assert "no-console-log" in violations
        assert violations["no-console-log"][0].line == 2


class TestScanRepo:
    def test_scan_finds_violations_across_files(self, tmp_path):
        root = _setup(tmp_path, ["no-print-statements"])
        src = tmp_path / "src"
        src.mkdir()
        (src / "a.py").write_text("print('hello')\n")
        (src / "b.py").write_text("x = 1\n")
        (src / "c.py").write_text("print('world')\nprint('!')\n")

        results = scan_repo(tmp_path)
        paths = {str(p) for p in results}
        assert str(src / "a.py") in paths
        assert str(src / "b.py") not in paths
        assert str(src / "c.py") in paths

    def test_scan_respects_binary_extension_skip(self, tmp_path):
        root = _setup(tmp_path, ["no-print-statements"])
        (tmp_path / "binary.pyc").write_bytes(b"\x00\x01\x02")
        results = scan_repo(tmp_path)
        assert not any(str(p).endswith(".pyc") for p in results)
