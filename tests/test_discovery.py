"""Tests for discovery.py — stack detection and drift checking."""

import json
import pytest
from pathlib import Path

from agentmd.discovery import discover, check_drift, DiscoveredContext
from agentmd.models import AgentsFile


class TestDiscover:
    def test_detects_python_from_pyproject(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "myapp"\ndependencies = ["fastapi>=0.100", "pydantic>=2"]\n'
        )
        ctx = discover(tmp_path)
        assert "python" in ctx.stack
        assert "fastapi" in ctx.stack
        assert "pydantic" in ctx.stack

    def test_detects_nodejs_from_package_json(self, tmp_path):
        (tmp_path / "package.json").write_text(
            json.dumps({"dependencies": {"react": "^18.0", "typescript": "^5.0"}})
        )
        ctx = discover(tmp_path)
        assert "nodejs" in ctx.stack
        assert "react" in ctx.stack
        assert "typescript" in ctx.stack

    def test_detects_go(self, tmp_path):
        (tmp_path / "go.mod").write_text("module example.com/myapp\n\ngo 1.21\n")
        ctx = discover(tmp_path)
        assert "go" in ctx.stack

    def test_detects_rust(self, tmp_path):
        (tmp_path / "Cargo.toml").write_text('[package]\nname = "myapp"\nversion = "0.1.0"\n')
        ctx = discover(tmp_path)
        assert "rust" in ctx.stack

    def test_empty_project(self, tmp_path):
        ctx = discover(tmp_path)
        assert ctx.stack == []

    def test_detects_uv_package_manager(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n')
        (tmp_path / "uv.lock").write_text("")
        ctx = discover(tmp_path)
        assert "uv" in ctx.package_managers

    def test_detects_pnpm(self, tmp_path):
        (tmp_path / "package.json").write_text(json.dumps({"dependencies": {}}))
        (tmp_path / "pnpm-lock.yaml").write_text("")
        ctx = discover(tmp_path)
        assert "pnpm" in ctx.package_managers

    def test_deduplicates_stack(self, tmp_path):
        # Both pyproject and requirements.txt declare fastapi
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "x"\ndependencies = ["fastapi"]\n'
        )
        (tmp_path / "requirements.txt").write_text("fastapi\n")
        ctx = discover(tmp_path)
        assert ctx.stack.count("fastapi") == 1

    def test_detects_eslint_convention(self, tmp_path):
        (tmp_path / "package.json").write_text(json.dumps({"dependencies": {}}))
        (tmp_path / ".eslintrc.json").write_text("{}")
        ctx = discover(tmp_path)
        assert any("ESLint" in c for c in ctx.linter_conventions)

    def test_requirements_txt_detection(self, tmp_path):
        (tmp_path / "requirements.txt").write_text("django>=4.0\ncelery\n")
        ctx = discover(tmp_path)
        assert "python" in ctx.stack
        assert "django" in ctx.stack
        assert "celery" in ctx.stack


class TestCheckDrift:
    def _make_agents(self, **kwargs) -> AgentsFile:
        base = {
            "agentmd": "1.0",
            "type": "agents",
            "name": "Test",
            "stack": [],
            "conventions": [],
        }
        base.update(kwargs)
        return AgentsFile.model_validate(base)

    def test_undeclared_stack_flagged(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "x"\ndependencies = ["fastapi"]\n'
        )
        agents = self._make_agents(stack=["python"])  # fastapi missing
        issues = check_drift(agents, tmp_path)
        assert any(i.kind == "undeclared_stack" and "fastapi" in i.message for i in issues)

    def test_declared_stack_matches_no_drift(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "x"\ndependencies = ["fastapi"]\n'
        )
        agents = self._make_agents(stack=["python", "fastapi"])
        issues = check_drift(agents, tmp_path)
        assert not any(i.kind == "undeclared_stack" for i in issues)

    def test_no_project_files_no_drift(self, tmp_path):
        agents = self._make_agents(stack=["python"])
        issues = check_drift(agents, tmp_path)
        assert issues == []

    def test_eslint_convention_gap(self, tmp_path):
        (tmp_path / "package.json").write_text(json.dumps({"dependencies": {}}))
        (tmp_path / ".eslintrc.json").write_text("{}")
        agents = self._make_agents(stack=["nodejs"], conventions=["Use camelCase"])
        issues = check_drift(agents, tmp_path)
        assert any(i.kind == "convention_gap" for i in issues)

    def test_eslint_mentioned_no_gap(self, tmp_path):
        (tmp_path / "package.json").write_text(json.dumps({"dependencies": {}}))
        (tmp_path / ".eslintrc.json").write_text("{}")
        agents = self._make_agents(
            stack=["nodejs"], conventions=["ESLint configured for linting"]
        )
        issues = check_drift(agents, tmp_path)
        assert not any(i.kind == "convention_gap" for i in issues)
