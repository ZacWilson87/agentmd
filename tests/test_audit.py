"""Tests for auditor.py and the CLI audit/trust/mcp commands."""

import json
import pytest
from pathlib import Path
from typer.testing import CliRunner

from agentmd.cli import app
from agentmd.auditor import run_audit

runner = CliRunner()

AGENTS = """\
---
agentmd: "1.0"
type: agents
name: "Test Project"
stack:
  - python
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

SKILL = """\
---
agentmd: "1.0"
type: skill
id: my-skill
version: "1.0"
description: "A skill"
trigger: "do the thing"
---
"""


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


class TestRunAudit:
    def test_clean_repo_passes(self, tmp_path):
        _write(tmp_path / "AGENTS.md", AGENTS)
        _write(tmp_path / "rules" / "no-print-statements.rule.md", RULE_NO_PRINT)
        _write(tmp_path / "src" / "app.py", "x = 1\n")

        report = run_audit(tmp_path)
        assert report.passed
        assert len(report.validation_errors) == 0
        assert report.error_violations == 0

    def test_detects_violations(self, tmp_path):
        _write(tmp_path / "AGENTS.md", AGENTS)
        _write(tmp_path / "rules" / "no-print-statements.rule.md", RULE_NO_PRINT)
        _write(tmp_path / "src" / "app.py", "print('debug')\n")

        report = run_audit(tmp_path)
        assert not report.passed
        assert report.error_violations > 0

    def test_detects_schema_errors(self, tmp_path):
        _write(tmp_path / "AGENTS.md", "---\nagentmd: '2.0'\ntype: agents\nname: X\n---\n")

        report = run_audit(tmp_path)
        assert len(report.validation_errors) == 1

    def test_reports_untrusted_skills(self, tmp_path):
        _write(tmp_path / "AGENTS.md", AGENTS)
        _write(tmp_path / "skills" / "my-skill.skill.md", SKILL)

        report = run_audit(tmp_path)
        assert len(report.untrusted_skills) == 1
        assert report.untrusted_skills[0].status == "new"

    def test_to_dict_structure(self, tmp_path):
        _write(tmp_path / "AGENTS.md", AGENTS)
        report = run_audit(tmp_path)
        d = report.to_dict()
        assert "passed" in d
        assert "summary" in d
        assert "validation" in d
        assert "violations" in d
        assert "drift" in d
        assert "trust" in d


class TestAuditCLI:
    def test_audit_clean_repo(self, tmp_path):
        _write(tmp_path / "AGENTS.md", AGENTS)
        result = runner.invoke(app, ["audit", str(tmp_path)])
        assert result.exit_code == 0
        assert "passed" in result.stdout.lower()

    def test_audit_json_output(self, tmp_path):
        _write(tmp_path / "AGENTS.md", AGENTS)
        result = runner.invoke(app, ["audit", "--json", str(tmp_path)])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert "passed" in data
        assert "summary" in data

    def test_audit_fails_on_violations(self, tmp_path):
        _write(tmp_path / "AGENTS.md", AGENTS)
        _write(tmp_path / "rules" / "no-print-statements.rule.md", RULE_NO_PRINT)
        _write(tmp_path / "src" / "bad.py", "print('oops')\n")
        result = runner.invoke(app, ["audit", str(tmp_path)])
        assert result.exit_code == 1


class TestTrustCLI:
    def test_trust_add(self, tmp_path):
        skill_file = tmp_path / "my.skill.md"
        skill_file.write_text(SKILL)
        result = runner.invoke(app, ["trust", "add", str(skill_file), "--root", str(tmp_path)])
        assert result.exit_code == 0
        assert "trusted" in result.stdout

    def test_trust_status(self, tmp_path):
        _write(tmp_path / "skills" / "my-skill.skill.md", SKILL)
        result = runner.invoke(app, ["trust", "status", str(tmp_path)])
        assert result.exit_code == 0
        assert "new" in result.stdout

    def test_trust_remove(self, tmp_path):
        skill_file = tmp_path / "my.skill.md"
        skill_file.write_text(SKILL)
        runner.invoke(app, ["trust", "add", str(skill_file), "--root", str(tmp_path)])
        result = runner.invoke(app, ["trust", "remove", str(skill_file), "--root", str(tmp_path)])
        assert result.exit_code == 0
        assert "removed" in result.stdout


class TestCheckCLIEnhanced:
    def test_check_shows_line_numbers(self, tmp_path):
        _write(tmp_path / "AGENTS.md", AGENTS)
        _write(tmp_path / "rules" / "no-print-statements.rule.md", RULE_NO_PRINT)
        py_file = tmp_path / "app.py"
        py_file.write_text("x = 1\nprint('oops')\ny = 2\n")
        result = runner.invoke(app, ["check", str(py_file)])
        assert result.exit_code == 1
        assert "line 2" in result.stdout

    def test_check_passes_clean_file(self, tmp_path):
        _write(tmp_path / "AGENTS.md", AGENTS)
        _write(tmp_path / "rules" / "no-print-statements.rule.md", RULE_NO_PRINT)
        py_file = tmp_path / "app.py"
        py_file.write_text("x = 1\n")
        result = runner.invoke(app, ["check", str(py_file)])
        assert result.exit_code == 0


class TestImmutableRules:
    """Tests for immutable rule precedence in resolver."""

    def test_immutable_rule_not_displaced(self, tmp_path):
        from agentmd.resolver import resolve

        # Root-level immutable rule
        _write(
            tmp_path / "rules" / "no-raw-sql.rule.md",
            "---\nagentmd: '1.0'\ntype: rule\nid: no-raw-sql\n"
            "severity: error\ndescription: 'no SQL (immutable)'\n"
            "applies_to:\n  - '**/*.py'\nimmutable: true\n---\n",
        )
        # Nested override attempt (non-immutable, same ID, closer scope)
        _write(
            tmp_path / "backend" / "rules" / "no-raw-sql.rule.md",
            "---\nagentmd: '1.0'\ntype: rule\nid: no-raw-sql\n"
            "severity: info\ndescription: 'overridden to info'\n"
            "applies_to:\n  - '**/*.py'\n---\n",
        )
        target = tmp_path / "backend" / "app.py"
        _write(target, "x = 1\n")

        ctx = resolve(target)
        sql_rules = [r for r in ctx.active_rules if r.id == "no-raw-sql"]
        assert len(sql_rules) == 1
        # Immutable root rule wins over non-immutable closer rule
        assert sql_rules[0].immutable is True
        assert sql_rules[0].severity == "error"

    def test_non_immutable_closest_wins(self, tmp_path):
        from agentmd.resolver import resolve

        # Root-level non-immutable rule
        _write(
            tmp_path / "rules" / "no-raw-sql.rule.md",
            "---\nagentmd: '1.0'\ntype: rule\nid: no-raw-sql\n"
            "severity: warning\ndescription: 'warning at root'\n"
            "applies_to:\n  - '**/*.py'\n---\n",
        )
        # Closer-scope override (also non-immutable)
        _write(
            tmp_path / "backend" / "rules" / "no-raw-sql.rule.md",
            "---\nagentmd: '1.0'\ntype: rule\nid: no-raw-sql\n"
            "severity: error\ndescription: 'error in backend'\n"
            "applies_to:\n  - '**/*.py'\n---\n",
        )
        target = tmp_path / "backend" / "app.py"
        _write(target, "x = 1\n")

        ctx = resolve(target)
        sql_rules = [r for r in ctx.active_rules if r.id == "no-raw-sql"]
        assert len(sql_rules) == 1
        # Closest non-immutable wins
        assert sql_rules[0].severity == "error"


class TestDeepMerge:
    """Tests for additive stack/conventions merge across multiple AGENTS.md."""

    def test_merged_stack_combines_all_agents_md(self, tmp_path):
        from agentmd.resolver import resolve

        _write(
            tmp_path / "AGENTS.md",
            "---\nagentmd: '1.0'\ntype: agents\nname: Root\nstack:\n  - python\n---\n",
        )
        _write(
            tmp_path / "backend" / "AGENTS.md",
            "---\nagentmd: '1.0'\ntype: agents\nname: Backend\nstack:\n  - fastapi\n---\n",
        )
        target = tmp_path / "backend" / "app.py"
        _write(target, "x = 1\n")

        ctx = resolve(target)
        # agents_file (closest) is Backend
        assert ctx.agents_file.name == "Backend"
        # merged_stack includes both
        assert "python" in ctx.merged_stack
        assert "fastapi" in ctx.merged_stack

    def test_merged_conventions_deduplicated(self, tmp_path):
        from agentmd.resolver import resolve

        _write(
            tmp_path / "AGENTS.md",
            "---\nagentmd: '1.0'\ntype: agents\nname: Root\nconventions:\n  - snake_case\n---\n",
        )
        _write(
            tmp_path / "sub" / "AGENTS.md",
            "---\nagentmd: '1.0'\ntype: agents\nname: Sub\nconventions:\n  - snake_case\n  - type hints\n---\n",
        )
        target = tmp_path / "sub" / "app.py"
        _write(target, "x = 1\n")

        ctx = resolve(target)
        assert ctx.merged_conventions.count("snake_case") == 1
        assert "type hints" in ctx.merged_conventions


class TestMCPServer:
    """Unit tests for the MCP server dispatch logic."""

    def test_initialize(self):
        from agentmd.mcp_server import _dispatch

        msg = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
        response = _dispatch(msg)
        assert response["id"] == 1
        assert response["result"]["serverInfo"]["name"] == "agentmd"
        assert "protocolVersion" in response["result"]

    def test_tools_list(self):
        from agentmd.mcp_server import _dispatch, TOOLS

        msg = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
        response = _dispatch(msg)
        assert response["id"] == 2
        tool_names = {t["name"] for t in response["result"]["tools"]}
        assert "agentmd_resolve" in tool_names
        assert "agentmd_list_skills" in tool_names
        assert "agentmd_audit" in tool_names

    def test_unknown_method_error(self):
        from agentmd.mcp_server import _dispatch

        msg = {"jsonrpc": "2.0", "id": 3, "method": "nonexistent", "params": {}}
        response = _dispatch(msg)
        assert "error" in response
        assert response["error"]["code"] == -32601

    def test_notification_no_response(self):
        from agentmd.mcp_server import _dispatch

        msg = {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
        response = _dispatch(msg)
        assert response is None

    def test_unknown_tool_call_error(self):
        from agentmd.mcp_server import _dispatch

        msg = {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "nonexistent_tool", "arguments": {}},
        }
        response = _dispatch(msg)
        assert "error" in response
