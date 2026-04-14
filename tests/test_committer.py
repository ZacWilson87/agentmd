"""Tests for agentmd/committer.py — CommitAnalysis, scope/type inference, analyze_staged."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agentmd.committer import (
    CommitAnalysis,
    CommitViolation,
    _suggest_scope,
    _suggest_type,
    get_staged_files,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write(path: Path, content: str = "x = 1\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def _violation(
    file: Path,
    rule_id: str = "test-rule",
    severity: str = "error",
    message: str = "violation",
    line: int | None = None,
) -> CommitViolation:
    return CommitViolation(
        file=file, rule_id=rule_id, severity=severity, message=message, line=line
    )


# ---------------------------------------------------------------------------
# CommitViolation
# ---------------------------------------------------------------------------


class TestCommitViolation:
    def test_fields_stored(self, tmp_path):
        f = tmp_path / "x.py"
        v = CommitViolation(file=f, rule_id="no-raw-sql", severity="critical", message="bad", line=5)
        assert v.file == f
        assert v.rule_id == "no-raw-sql"
        assert v.severity == "critical"
        assert v.message == "bad"
        assert v.line == 5

    def test_line_defaults_to_none(self, tmp_path):
        v = CommitViolation(file=tmp_path / "x.py", rule_id="r", severity="error", message="m")
        assert v.line is None


# ---------------------------------------------------------------------------
# CommitAnalysis
# ---------------------------------------------------------------------------


class TestCommitAnalysis:
    def _analysis(self, violations: list[CommitViolation], tmp_path: Path) -> CommitAnalysis:
        return CommitAnalysis(
            staged_files=[tmp_path / "x.py"],
            violations=violations,
            suggested_scope="db",
            suggested_type="feat",
        )

    def test_critical_violations_filtered(self, tmp_path):
        f = tmp_path / "x.py"
        vs = [
            _violation(f, severity="critical"),
            _violation(f, severity="error"),
            _violation(f, severity="warning"),
        ]
        analysis = self._analysis(vs, tmp_path)
        assert len(analysis.critical_violations) == 1
        assert analysis.critical_violations[0].severity == "critical"

    def test_error_violations_includes_critical(self, tmp_path):
        f = tmp_path / "x.py"
        vs = [
            _violation(f, severity="critical"),
            _violation(f, severity="error"),
            _violation(f, severity="info"),
        ]
        analysis = self._analysis(vs, tmp_path)
        assert len(analysis.error_violations) == 2

    def test_is_blocked_true_when_critical(self, tmp_path):
        f = tmp_path / "x.py"
        analysis = self._analysis([_violation(f, severity="critical")], tmp_path)
        assert analysis.is_blocked is True

    def test_is_blocked_false_when_no_critical(self, tmp_path):
        f = tmp_path / "x.py"
        analysis = self._analysis([_violation(f, severity="error")], tmp_path)
        assert analysis.is_blocked is False

    def test_is_blocked_false_with_no_violations(self, tmp_path):
        analysis = self._analysis([], tmp_path)
        assert analysis.is_blocked is False

    def test_format_message_with_scope(self, tmp_path):
        analysis = CommitAnalysis(
            staged_files=[], violations=[], suggested_scope="db", suggested_type="feat"
        )
        msg = analysis.format_message("add user schema")
        assert msg == "feat(db): add user schema"

    def test_format_message_without_scope(self, tmp_path):
        analysis = CommitAnalysis(
            staged_files=[], violations=[], suggested_scope=None, suggested_type="fix"
        )
        msg = analysis.format_message("correct off-by-one")
        assert msg == "fix: correct off-by-one"

    def test_format_message_default_description(self, tmp_path):
        analysis = CommitAnalysis(
            staged_files=[], violations=[], suggested_scope="api", suggested_type="feat"
        )
        msg = analysis.format_message()
        assert msg == "feat(api): <description>"

    def test_contexts_defaults_empty(self):
        analysis = CommitAnalysis(
            staged_files=[], violations=[], suggested_scope=None, suggested_type="chore"
        )
        assert analysis.contexts == {}


# ---------------------------------------------------------------------------
# _suggest_type
# ---------------------------------------------------------------------------


class TestSuggestType:
    def test_all_markdown_returns_docs(self, tmp_path):
        files = [tmp_path / "README.md", tmp_path / "docs" / "spec.md"]
        assert _suggest_type(files, {}) == "docs"

    def test_docs_path_returns_docs(self, tmp_path):
        files = [tmp_path / "docs" / "intro.rst"]
        assert _suggest_type(files, {}) == "docs"

    def test_all_tests_returns_test(self, tmp_path):
        files = [tmp_path / "tests" / "test_foo.py", tmp_path / "tests" / "test_bar.py"]
        assert _suggest_type(files, {}) == "test"

    def test_test_prefix_file_returns_test(self, tmp_path):
        files = [tmp_path / "test_util.py"]
        assert _suggest_type(files, {}) == "test"

    def test_config_files_return_chore(self, tmp_path):
        files = [tmp_path / "pyproject.toml", tmp_path / ".gitignore"]
        assert _suggest_type(files, {}) == "chore"

    def test_all_modifications_returns_fix(self, tmp_path):
        f = tmp_path / "app.py"
        # Status map uses basename → status
        status_map = {f.name: "M"}
        assert _suggest_type([f], status_map) == "fix"

    def test_default_returns_feat(self, tmp_path):
        files = [tmp_path / "agentmd" / "new_module.py"]
        assert _suggest_type(files, {}) == "feat"

    def test_empty_staged_returns_chore(self):
        assert _suggest_type([], {}) == "chore"


# ---------------------------------------------------------------------------
# _suggest_scope
# ---------------------------------------------------------------------------


class TestSuggestScope:
    def _make_ctx(self, tags: list[str], scope: str = "project"):
        from agentmd.models import AgentsFile, SkillFile
        from agentmd.resolver import ResolvedContext

        ctx = ResolvedContext()
        ctx.active_skills = []
        for tag in tags:
            skill = SkillFile(
                agentmd="1.0", type="skill", id=f"skill-{tag}",
                version="1.0", description="Test skill", trigger="on demand",
                tags=[tag],
            )
            ctx.active_skills.append(skill)
        if scope != "project":
            ctx.agents_file = AgentsFile(
                agentmd="1.0", type="agents", name="pkg", scope=scope,
            )
        return ctx

    def test_skill_tag_wins(self, tmp_path):
        f = tmp_path / "agentmd" / "cli.py"
        ctx = self._make_ctx(tags=["cli"])
        contexts = {str(f): ctx}
        result = _suggest_scope([f], contexts, tmp_path)
        assert result == "cli"

    def test_most_frequent_tag_wins(self, tmp_path):
        f1 = tmp_path / "agentmd" / "cli.py"
        f2 = tmp_path / "agentmd" / "models.py"
        ctx1 = self._make_ctx(tags=["db"])
        ctx2 = self._make_ctx(tags=["db", "api"])
        contexts = {str(f1): ctx1, str(f2): ctx2}
        result = _suggest_scope([f1, f2], contexts, tmp_path)
        assert result == "db"  # "db" appears twice, "api" once

    def test_common_subdirectory_fallback(self, tmp_path):
        f1 = _write(tmp_path / "agentmd" / "cli.py")
        f2 = _write(tmp_path / "agentmd" / "models.py")
        from agentmd.resolver import ResolvedContext

        ctx = ResolvedContext()  # no skills, no package scope
        contexts = {str(f1): ctx, str(f2): ctx}
        result = _suggest_scope([f1, f2], contexts, tmp_path)
        assert result == "agentmd"

    def test_no_signal_returns_none(self, tmp_path):
        f1 = _write(tmp_path / "src" / "a.py")
        f2 = _write(tmp_path / "tests" / "b.py")
        from agentmd.resolver import ResolvedContext

        ctx = ResolvedContext()
        contexts = {str(f1): ctx, str(f2): ctx}
        result = _suggest_scope([f1, f2], contexts, tmp_path)
        assert result is None

    def test_empty_staged_returns_none(self, tmp_path):
        result = _suggest_scope([], {}, tmp_path)
        assert result is None

    def test_non_resolved_context_skipped(self, tmp_path):
        f = _write(tmp_path / "agentmd" / "cli.py")
        # Non-ResolvedContext objects are skipped; falls through to common subdir
        contexts = {str(f): "not-a-context"}
        result = _suggest_scope([f], contexts, tmp_path)
        assert result == "agentmd"


# ---------------------------------------------------------------------------
# get_staged_files
# ---------------------------------------------------------------------------


class TestGetStagedFiles:
    def test_returns_empty_when_git_not_available(self, tmp_path):
        with patch("agentmd.committer.subprocess.run", side_effect=FileNotFoundError):
            result = get_staged_files(tmp_path)
        assert result == []

    def test_returns_empty_when_nonzero_exit(self, tmp_path):
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        with patch("agentmd.committer.subprocess.run", return_value=mock_result):
            result = get_staged_files(tmp_path)
        assert result == []

    def test_returns_empty_when_no_staged_files(self, tmp_path):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        with patch("agentmd.committer.subprocess.run", return_value=mock_result):
            result = get_staged_files(tmp_path)
        assert result == []

    def test_returns_existing_files_only(self, tmp_path):
        existing = _write(tmp_path / "app.py")
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "app.py\nnonexistent.py\n"
        with patch("agentmd.committer.subprocess.run", return_value=mock_result):
            result = get_staged_files(tmp_path)
        # Only the file that actually exists on disk is returned
        assert len(result) == 1
        assert result[0] == existing.resolve()

    def test_timeout_returns_empty(self, tmp_path):
        import subprocess as _sp
        with patch("agentmd.committer.subprocess.run", side_effect=_sp.TimeoutExpired("git", 10)):
            result = get_staged_files(tmp_path)
        assert result == []


# ---------------------------------------------------------------------------
# analyze_staged — light integration (no real git; mock staged files)
# ---------------------------------------------------------------------------


class TestAnalyzeStaged:
    def test_no_staged_files_returns_empty_analysis(self, tmp_path):
        with patch("agentmd.committer.get_staged_files", return_value=[]), \
             patch("agentmd.committer._git_status_map", return_value={}):
            from agentmd.committer import analyze_staged
            result = analyze_staged(tmp_path)
        assert result.staged_files == []
        assert result.violations == []
        assert result.is_blocked is False

    def test_staged_file_with_violation_is_collected(self, tmp_path):
        target = _write(tmp_path / "app.py", 'print("hello")\n')
        # Use a real rule that has a built-in checker (no-print-statements)
        from agentmd.models import RuleFile
        from agentmd.resolver import ResolvedContext

        rule = RuleFile(
            agentmd="1.0", type="rule", id="no-print-statements",
            severity="error", description="No prints",
        )
        ctx = ResolvedContext()
        ctx.active_rules = [rule]

        with patch("agentmd.committer.get_staged_files", return_value=[target]), \
             patch("agentmd.committer._git_status_map", return_value={}), \
             patch("agentmd.resolver.resolve", return_value=ctx):
            from agentmd.committer import analyze_staged
            result = analyze_staged(tmp_path)

        assert len(result.staged_files) == 1
        assert len(result.violations) >= 1
        assert any(v.rule_id == "no-print-statements" for v in result.violations)

    def test_critical_violation_sets_is_blocked(self, tmp_path):
        target = _write(tmp_path / "creds.py", 'SECRET_KEY = "abc"\n')
        from agentmd.models import RuleFile
        from agentmd.resolver import ResolvedContext

        rule = RuleFile(
            agentmd="1.0", type="rule", id="no-secrets",
            severity="critical", description="No secrets",
            linter_regex=r'SECRET_KEY\s*=',
        )
        ctx = ResolvedContext()
        ctx.active_rules = [rule]

        with patch("agentmd.committer.get_staged_files", return_value=[target]), \
             patch("agentmd.committer._git_status_map", return_value={}), \
             patch("agentmd.resolver.resolve", return_value=ctx):
            from agentmd.committer import analyze_staged
            result = analyze_staged(tmp_path)

        assert result.is_blocked is True
        assert any(v.severity == "critical" for v in result.violations)

    def test_clean_file_no_violations(self, tmp_path):
        target = _write(tmp_path / "util.py", "x: int = 1\n")
        from agentmd.models import RuleFile
        from agentmd.resolver import ResolvedContext

        rule = RuleFile(
            agentmd="1.0", type="rule", id="no-todo",
            severity="warning", description="No TODOs",
            linter_regex=r"TODO",
        )
        ctx = ResolvedContext()
        ctx.active_rules = [rule]

        with patch("agentmd.committer.get_staged_files", return_value=[target]), \
             patch("agentmd.committer._git_status_map", return_value={}), \
             patch("agentmd.resolver.resolve", return_value=ctx):
            from agentmd.committer import analyze_staged
            result = analyze_staged(tmp_path)

        assert result.violations == []
        assert result.is_blocked is False

    def test_suggested_type_from_staged_files(self, tmp_path):
        target = _write(tmp_path / "tests" / "test_foo.py")
        from agentmd.resolver import ResolvedContext

        ctx = ResolvedContext()
        ctx.active_rules = []

        with patch("agentmd.committer.get_staged_files", return_value=[target]), \
             patch("agentmd.committer._git_status_map", return_value={}), \
             patch("agentmd.resolver.resolve", return_value=ctx):
            from agentmd.committer import analyze_staged
            result = analyze_staged(tmp_path)

        assert result.suggested_type == "test"
