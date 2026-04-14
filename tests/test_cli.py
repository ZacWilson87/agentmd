"""Tests for the agentmd CLI commands."""

import json
import pytest
from pathlib import Path
from typer.testing import CliRunner

from agentmd.cli import app

runner = CliRunner()


AGENTS_CONTENT = """\
---
agentmd: "1.0"
type: agents
name: "Test Project"
scope: project
stack:
  - python
---

# Test Project
"""

SKILL_CONTENT = """\
---
agentmd: "1.0"
type: skill
id: scaffold-component
version: "1.0"
description: "Scaffold a component"
trigger: "when asked to scaffold"
tags:
  - frontend
---

## Steps
"""

RULE_CONTENT = """\
---
agentmd: "1.0"
type: rule
id: no-raw-sql
severity: error
description: "No raw SQL"
applies_to:
  - "**/*.py"
---

## Rule
"""


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


class TestVersion:
    def test_version(self):
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert "agentmd" in result.stdout


class TestHelp:
    def test_help(self):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "agentmd" in result.stdout


class TestInit:
    def test_init_creates_files(self, tmp_path):
        result = runner.invoke(app, ["init", str(tmp_path)])
        assert result.exit_code == 0
        assert (tmp_path / "AGENTS.md").exists()
        assert (tmp_path / "skills").is_dir()
        assert (tmp_path / "rules").is_dir()

    def test_init_idempotent_without_force(self, tmp_path):
        runner.invoke(app, ["init", str(tmp_path)])
        # Second run without --force should report nothing to do
        result = runner.invoke(app, ["init", str(tmp_path)])
        assert result.exit_code == 0
        assert "Nothing to do" in result.stdout

    def test_init_force_overwrites(self, tmp_path):
        runner.invoke(app, ["init", str(tmp_path)])
        result = runner.invoke(app, ["init", "--force", str(tmp_path)])
        assert result.exit_code == 0
        assert "created" in result.stdout


class TestValidate:
    def test_validate_valid_files(self, tmp_path):
        _write(tmp_path / "AGENTS.md", AGENTS_CONTENT)
        _write(tmp_path / "skills" / "scaffold-component.skill.md", SKILL_CONTENT)
        _write(tmp_path / "rules" / "no-raw-sql.rule.md", RULE_CONTENT)
        result = runner.invoke(app, ["validate", str(tmp_path)])
        assert result.exit_code == 0
        assert "valid" in result.stdout

    def test_validate_invalid_file(self, tmp_path):
        _write(tmp_path / "AGENTS.md", "---\nagentmd: '2.0'\ntype: agents\nname: X\n---\n")
        result = runner.invoke(app, ["validate", str(tmp_path)])
        assert result.exit_code == 1
        assert "error" in result.stdout

    def test_validate_no_files(self, tmp_path):
        result = runner.invoke(app, ["validate", str(tmp_path)])
        assert result.exit_code == 0
        assert "No agentmd files" in result.stdout


class TestResolve:
    def test_resolve_shows_context(self, tmp_path):
        _write(tmp_path / "AGENTS.md", AGENTS_CONTENT)
        target = tmp_path / "src" / "main.py"
        target.parent.mkdir()
        target.touch()
        result = runner.invoke(app, ["resolve", str(target)])
        assert result.exit_code == 0
        assert "Test Project" in result.stdout

    def test_resolve_json(self, tmp_path):
        _write(tmp_path / "AGENTS.md", AGENTS_CONTENT)
        target = tmp_path / "src" / "main.py"
        target.parent.mkdir()
        target.touch()
        result = runner.invoke(app, ["resolve", "--json", str(target)])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["agents_file"]["name"] == "Test Project"


class TestListSkills:
    def test_list_skills(self, tmp_path):
        _write(tmp_path / "AGENTS.md", AGENTS_CONTENT)
        _write(tmp_path / "skills" / "scaffold-component.skill.md", SKILL_CONTENT)
        result = runner.invoke(app, ["list", "skills", str(tmp_path)])
        assert result.exit_code == 0
        assert "scaffold-component" in result.stdout

    def test_list_skills_empty(self, tmp_path):
        result = runner.invoke(app, ["list", "skills", str(tmp_path)])
        assert result.exit_code == 0
        assert "No SKILL.md" in result.stdout


class TestListRules:
    def test_list_rules(self, tmp_path):
        _write(tmp_path / "AGENTS.md", AGENTS_CONTENT)
        _write(tmp_path / "rules" / "no-raw-sql.rule.md", RULE_CONTENT)
        result = runner.invoke(app, ["list", "rules", str(tmp_path)])
        assert result.exit_code == 0
        assert "no-raw-sql" in result.stdout

    def test_list_rules_empty(self, tmp_path):
        result = runner.invoke(app, ["list", "rules", str(tmp_path)])
        assert result.exit_code == 0
        assert "No RULE.md" in result.stdout


class TestAddSkill:
    def test_add_skill_creates_file(self, tmp_path):
        runner.invoke(app, ["init", str(tmp_path)])
        result = runner.invoke(app, ["add", "skill", "write-test", str(tmp_path)])
        assert result.exit_code == 0
        assert (tmp_path / "skills" / "write-test.skill.md").exists()

    def test_add_skill_registers_in_agents(self, tmp_path):
        runner.invoke(app, ["init", str(tmp_path)])
        runner.invoke(app, ["add", "skill", "write-test", str(tmp_path)])
        agents_text = (tmp_path / "AGENTS.md").read_text()
        assert "write-test.skill.md" in agents_text


class TestAddRule:
    def test_add_rule_creates_file(self, tmp_path):
        runner.invoke(app, ["init", str(tmp_path)])
        result = runner.invoke(app, ["add", "rule", "no-print-statements", str(tmp_path)])
        assert result.exit_code == 0
        assert (tmp_path / "rules" / "no-print-statements.rule.md").exists()

    def test_add_rule_registers_in_agents(self, tmp_path):
        runner.invoke(app, ["init", str(tmp_path)])
        runner.invoke(app, ["add", "rule", "no-print-statements", str(tmp_path)])
        agents_text = (tmp_path / "AGENTS.md").read_text()
        assert "no-print-statements.rule.md" in agents_text


class TestExport:
    def test_export_json(self, tmp_path):
        _write(tmp_path / "AGENTS.md", AGENTS_CONTENT)
        target = tmp_path / "src" / "main.py"
        target.parent.mkdir()
        target.touch()
        result = runner.invoke(app, ["export", str(target)])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert "agents_file" in data
        assert "active_skills" in data
        assert "active_rules" in data

    def test_export_to_file(self, tmp_path):
        _write(tmp_path / "AGENTS.md", AGENTS_CONTENT)
        target = tmp_path / "src" / "main.py"
        target.parent.mkdir()
        target.touch()
        out_file = tmp_path / "context.json"
        result = runner.invoke(app, ["export", str(target), "--output", str(out_file)])
        assert result.exit_code == 0
        assert out_file.exists()
        data = json.loads(out_file.read_text())
        assert data["agents_file"]["name"] == "Test Project"
