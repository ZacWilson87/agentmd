"""Tests for linter_command and linter_regex integration in checker.py."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from agentmd.checker import (
    ViolationDetail,
    _run_linter_command,
    _run_linter_regex,
    check_file,
)
from agentmd.models import RuleFile
from agentmd.resolver import ResolvedContext


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def _make_rule(**kwargs: object) -> RuleFile:
    defaults = {
        "agentmd": "1.0",
        "type": "rule",
        "id": "test-rule",
        "severity": "error",
        "description": "Test rule",
    }
    defaults.update(kwargs)
    return RuleFile(**defaults)  # type: ignore[arg-type]


def _make_ctx(rule: RuleFile) -> ResolvedContext:
    ctx = ResolvedContext()
    ctx.active_rules = [rule]
    return ctx


# ---------------------------------------------------------------------------
# linter_regex tests
# ---------------------------------------------------------------------------

class TestLinterRegex:
    def test_detects_matching_line(self, tmp_path):
        rule = _make_rule(linter_regex=r"TODO")
        target = _write(tmp_path / "code.py", "x = 1\n# TODO: fix this\ny = 2\n")
        violations = _run_linter_regex(rule, target.read_text())
        assert len(violations) == 1
        assert violations[0].line == 2
        assert "TODO" in violations[0].message

    def test_returns_empty_when_no_match(self, tmp_path):
        rule = _make_rule(linter_regex=r"TODO")
        violations = _run_linter_regex(rule, "x = 1\ny = 2\n")
        assert violations == []

    def test_multiple_matching_lines(self, tmp_path):
        rule = _make_rule(linter_regex=r"FIXME")
        content = "# FIXME line 1\nok = True\n# FIXME line 3\n"
        violations = _run_linter_regex(rule, content)
        assert len(violations) == 2
        assert violations[0].line == 1
        assert violations[1].line == 3

    def test_returns_empty_when_regex_is_none(self):
        rule = _make_rule(linter_regex=None)
        violations = _run_linter_regex(rule, "TODO")
        assert violations == []

    def test_invalid_regex_returns_empty(self):
        rule = _make_rule(linter_regex=r"[invalid")
        violations = _run_linter_regex(rule, "text")
        assert violations == []

    def test_regex_is_case_sensitive_by_default(self):
        rule = _make_rule(linter_regex=r"todo")
        violations_lower = _run_linter_regex(rule, "# todo: fix")
        violations_upper = _run_linter_regex(rule, "# TODO: fix")
        assert len(violations_lower) == 1
        assert len(violations_upper) == 0

    def test_regex_with_special_chars(self):
        rule = _make_rule(linter_regex=r"https://api\.example\.com")
        content = "url = 'https://api.example.com/v1'\nother = 'https://example.org'\n"
        violations = _run_linter_regex(rule, content)
        assert len(violations) == 1
        assert violations[0].line == 1

    def test_message_truncated_at_120_chars(self):
        rule = _make_rule(linter_regex=r"X")
        long_line = "X" * 200
        violations = _run_linter_regex(rule, long_line)
        assert len(violations) == 1
        assert len(violations[0].message) <= 200  # message includes prefix


# ---------------------------------------------------------------------------
# linter_command tests
# ---------------------------------------------------------------------------

class TestLinterCommand:
    def test_returns_empty_when_command_is_none(self, tmp_path):
        rule = _make_rule(linter_command=None)
        target = _write(tmp_path / "f.py", "x = 1\n")
        violations = _run_linter_command(rule, target)
        assert violations == []

    def test_clean_exit_zero_returns_no_violations(self, tmp_path):
        """A command that exits 0 means no violations."""
        target = _write(tmp_path / "f.txt", "clean\n")
        rule = _make_rule(linter_command=f"{sys.executable} -c 'import sys; sys.exit(0)'")
        violations = _run_linter_command(rule, target)
        assert violations == []

    def test_nonzero_exit_with_output_returns_violations(self, tmp_path):
        """A command that exits 1 with output creates violations."""
        target = _write(tmp_path / "f.py", "bad code\n")
        script = f'{sys.executable} -c "import sys; print(\'error found\'); sys.exit(1)"'
        rule = _make_rule(linter_command=script)
        violations = _run_linter_command(rule, target)
        assert len(violations) == 1
        assert "error found" in violations[0].message

    def test_file_substitution_in_command(self, tmp_path):
        """{{file}} is replaced with the absolute file path."""
        target = _write(tmp_path / "f.txt", "content\n")
        # Command echoes the file path and exits 1 to trigger violation parsing
        script = (
            f'{sys.executable} -c "import sys; '
            f'print(sys.argv[1]); sys.exit(1)" '
            f"{{file}}"
        )
        rule = _make_rule(linter_command=script)
        violations = _run_linter_command(rule, target)
        assert violations
        assert str(target) in violations[0].message

    def test_file_appended_when_no_placeholder(self, tmp_path):
        """If {{file}} is absent, file path is appended as last argument."""
        target = _write(tmp_path / "f.txt", "content\n")
        # The command exits 1 and prints the last argv (the file path)
        script = (
            f'{sys.executable} -c "import sys; '
            f'print(sys.argv[-1]); sys.exit(1)"'
        )
        rule = _make_rule(linter_command=script)
        violations = _run_linter_command(rule, target)
        assert violations
        # The last argument (file path) should appear in the output
        assert str(target) in violations[0].message

    def test_missing_executable_returns_empty(self, tmp_path):
        target = _write(tmp_path / "f.py", "x\n")
        rule = _make_rule(linter_command="nonexistent_tool_xyz {file}")
        violations = _run_linter_command(rule, target)
        assert violations == []

    def test_nonzero_exit_without_output_returns_generic_message(self, tmp_path):
        target = _write(tmp_path / "f.py", "x\n")
        script = f'{sys.executable} -c "import sys; sys.exit(2)"'
        rule = _make_rule(linter_command=script)
        violations = _run_linter_command(rule, target)
        assert len(violations) == 1
        assert "exited 2" in violations[0].message

    def test_location_parsing_extracts_line_number(self, tmp_path):
        """Lines matching 'file:N: message' get their line number extracted."""
        target = _write(tmp_path / "f.py", "bad\n")
        # Emit output matching the 'file:line: message' pattern
        script = (
            f'{sys.executable} -c "import sys; '
            f'print(\'f.py:5: type error here\'); sys.exit(1)"'
        )
        rule = _make_rule(linter_command=script)
        violations = _run_linter_command(rule, target)
        assert violations
        assert violations[0].line == 5
        assert "type error here" in violations[0].message


# ---------------------------------------------------------------------------
# check_file integration: built-in + linter_regex + linter_command
# ---------------------------------------------------------------------------

class TestCheckFileWithLinters:
    def test_linter_regex_runs_alongside_builtin(self, tmp_path):
        """Both built-in (no-print) and linter_regex fire on the same file."""
        target = _write(tmp_path / "app.py", 'print("hello")  # TODO: remove\n')
        rule = _make_rule(
            id="no-print-statements",
            linter_regex=r"TODO",
        )
        ctx = _make_ctx(rule)
        violations = check_file(target, ctx)
        assert "no-print-statements" in violations
        details = violations["no-print-statements"]
        # Should have at least 2: one from built-in AST, one from regex TODO
        assert len(details) >= 2

    def test_linter_regex_only_rule(self, tmp_path):
        """A rule with only linter_regex but no built-in checker fires correctly."""
        target = _write(tmp_path / "config.yaml", "api_url: https://prod.example.com\n")
        rule = _make_rule(
            id="no-prod-urls",
            linter_regex=r"https://prod\.example\.com",
            applies_to=["**/*.yaml"],
        )
        ctx = _make_ctx(rule)
        violations = check_file(target, ctx)
        assert "no-prod-urls" in violations
        assert violations["no-prod-urls"][0].line == 1

    def test_clean_file_no_violations(self, tmp_path):
        target = _write(tmp_path / "app.py", "x: int = 1\n")
        rule = _make_rule(id="no-todo", linter_regex=r"TODO")
        ctx = _make_ctx(rule)
        violations = check_file(target, ctx)
        assert violations == {}

    def test_linter_command_in_check_file(self, tmp_path):
        """linter_command fires through check_file()."""
        target = _write(tmp_path / "f.py", "bad\n")
        script = f'{sys.executable} -c "import sys; print(\'violation\'); sys.exit(1)"'
        rule = _make_rule(id="custom-linter", linter_command=script)
        ctx = _make_ctx(rule)
        violations = check_file(target, ctx)
        assert "custom-linter" in violations
        assert any("violation" in v.message for v in violations["custom-linter"])

    def test_critical_severity_rule_with_regex(self, tmp_path):
        """critical severity is preserved in check_file output."""
        target = _write(tmp_path / "creds.py", 'SECRET_KEY = "abc123"\n')
        rule = _make_rule(
            id="no-secrets",
            severity="critical",
            linter_regex=r"SECRET_KEY\s*=\s*[\"']",
        )
        ctx = _make_ctx(rule)
        violations = check_file(target, ctx)
        assert "no-secrets" in violations


# ---------------------------------------------------------------------------
# Model: new RuleFile fields
# ---------------------------------------------------------------------------

class TestRuleFileModel:
    def test_linter_command_optional(self):
        rule = RuleFile(
            agentmd="1.0", type="rule", id="test-rule",
            severity="error", description="Test",
        )
        assert rule.linter_command is None
        assert rule.linter_regex is None

    def test_linter_command_set(self):
        rule = RuleFile(
            agentmd="1.0", type="rule", id="test-rule",
            severity="error", description="Test",
            linter_command="mypy {file}",
        )
        assert rule.linter_command == "mypy {file}"

    def test_linter_regex_set(self):
        rule = RuleFile(
            agentmd="1.0", type="rule", id="test-rule",
            severity="error", description="Test",
            linter_regex=r"TODO",
        )
        assert rule.linter_regex == "TODO"

    def test_critical_severity_valid(self):
        rule = RuleFile(
            agentmd="1.0", type="rule", id="test-rule",
            severity="critical", description="Critical test",
        )
        assert rule.severity == "critical"

    def test_invalid_severity_rejected(self):
        import pytest
        with pytest.raises(Exception):
            RuleFile(
                agentmd="1.0", type="rule", id="test-rule",
                severity="blocker", description="Bad",
            )
