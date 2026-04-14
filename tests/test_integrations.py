"""Integration tests verifying the export format, integration scripts, and hooks.

These tests ensure that:
  1. export_context() produces the exact JSON shape that integration scripts consume.
  2. The Cursor, Copilot, and Windsurf generation script logic is correct.
  3. The CLI export command works as documented (including the --json flag).
  4. The agentmd project's own files validate and export cleanly (meta-showcase).
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from agentmd.cli import app
from agentmd.exporter import export_context
from agentmd.resolver import resolve

runner = CliRunner()

FLAT_FIXTURE = Path(__file__).parent / "fixtures" / "flat_repo"
NESTED_FIXTURE = Path(__file__).parent / "fixtures" / "nested_repo"
OWN_ROOT = Path(__file__).parent.parent  # /home/user/agentmd


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def _make_repo(tmp_path: Path) -> tuple[Path, Path]:
    """Create a minimal repo with AGENTS.md, one skill, one rule. Return (root, target)."""
    _write(tmp_path / "AGENTS.md", """\
---
agentmd: "1.0"
type: agents
name: "Test Project"
scope: project
stack:
  - python
  - fastapi
conventions:
  - "Use snake_case"
agent_instructions: "You are a FastAPI assistant."
skills:
  - skills/my-skill.skill.md
rules:
  - rules/no-raw-sql.rule.md
---
""")
    _write(tmp_path / "skills" / "my-skill.skill.md", """\
---
agentmd: "1.0"
type: skill
id: my-skill
version: "1.0"
description: "Do a thing"
trigger: "when asked to do the thing"
---

## Steps

1. Do it.
""")
    _write(tmp_path / "rules" / "no-raw-sql.rule.md", """\
---
agentmd: "1.0"
type: rule
id: no-raw-sql
severity: error
description: "No raw SQL strings"
rationale: "Prevents injection vulnerabilities"
applies_to:
  - "**/*.py"
exceptions:
  - "migrations/**"
---
""")
    target = tmp_path / "src" / "main.py"
    _write(target, "# main\n")
    return tmp_path, target


# ---------------------------------------------------------------------------
# TestExportSchema — verifies export_context() shape
# ---------------------------------------------------------------------------

class TestExportSchema:
    """Verify export_context() produces the exact shape integration scripts consume."""

    def test_export_has_all_top_level_keys(self, tmp_path):
        _, target = _make_repo(tmp_path)
        ctx = resolve(target)
        data = export_context(ctx)
        required = {
            "agents_file", "active_skills", "active_rules",
            "source_files", "merged_stack", "merged_conventions",
            "prompt_snippets", "warnings",
        }
        assert required.issubset(data.keys())

    def test_agents_file_has_script_fields(self, tmp_path):
        """Cursor and Copilot scripts access agent_instructions, conventions, stack."""
        _, target = _make_repo(tmp_path)
        data = export_context(resolve(target))
        a = data["agents_file"]
        assert "agent_instructions" in a
        assert isinstance(a["conventions"], list)
        assert isinstance(a["stack"], list)
        assert a["agent_instructions"] == "You are a FastAPI assistant."
        assert "Use snake_case" in a["conventions"]

    def test_rules_have_script_fields(self, tmp_path):
        """All scripts access id, severity, description, rationale, applies_to."""
        _, target = _make_repo(tmp_path)
        data = export_context(resolve(target))
        assert len(data["active_rules"]) > 0
        for rule in data["active_rules"]:
            for key in ("id", "severity", "description", "rationale", "applies_to"):
                assert key in rule, f"Rule missing key: {key}"
            assert isinstance(rule["applies_to"], list)

    def test_skills_have_path_field(self, tmp_path):
        """Bug 2 regression guard: active_skills must include a path field."""
        _, target = _make_repo(tmp_path)
        data = export_context(resolve(target))
        assert len(data["active_skills"]) > 0
        for skill in data["active_skills"]:
            assert "path" in skill, "Skill missing 'path' field (Bug 2)"
            assert skill["path"] is not None
            assert skill["path"].endswith(".skill.md")

    def test_skill_path_is_absolute(self, tmp_path):
        _, target = _make_repo(tmp_path)
        data = export_context(resolve(target))
        for skill in data["active_skills"]:
            assert Path(skill["path"]).is_absolute()

    def test_skills_have_id_description_trigger(self, tmp_path):
        """Windsurf script accesses id, description, trigger."""
        _, target = _make_repo(tmp_path)
        data = export_context(resolve(target))
        for skill in data["active_skills"]:
            for key in ("id", "description", "trigger"):
                assert key in skill

    def test_prompt_snippets_present(self, tmp_path):
        _, target = _make_repo(tmp_path)
        data = export_context(resolve(target))
        assert isinstance(data["prompt_snippets"], list)
        assert len(data["prompt_snippets"]) == len(data["active_skills"])
        for snippet in data["prompt_snippets"]:
            assert "Trigger:" in snippet
            assert ".skill.md" in snippet

    def test_export_with_no_agentmd_returns_valid_shape(self, tmp_path):
        """Graceful empty-repo case: all keys present, agents_file is None."""
        empty_file = tmp_path / "empty.py"
        empty_file.write_text("# nothing\n")
        data = export_context(resolve(empty_file))
        assert data["agents_file"] is None
        assert data["active_skills"] == []
        assert data["active_rules"] == []
        assert data["prompt_snippets"] == []

    def test_flat_fixture_exports_correctly(self, tmp_path):
        """Use the checked-in flat_repo fixture as a real-world test.
        Resolves against a .py file so the no-raw-sql rule (applies_to **/*.py) matches.
        """
        import shutil
        repo = tmp_path / "flat_repo"
        shutil.copytree(FLAT_FIXTURE, repo)
        py_target = repo / "main.py"
        py_target.write_text("# test\n")
        data = export_context(resolve(py_target))
        assert data["agents_file"]["name"] == "Flat Repo Example"
        assert any(s["id"] == "scaffold-endpoint" for s in data["active_skills"])
        assert any(r["id"] == "no-raw-sql" for r in data["active_rules"])


# ---------------------------------------------------------------------------
# TestCLIExportCommand — verifies CLI export command behaviour
# ---------------------------------------------------------------------------

class TestCLIExportCommand:
    """Verify the CLI export command works as documented (including --json flag)."""

    def test_export_stdout_is_valid_json(self, tmp_path):
        _, target = _make_repo(tmp_path)
        result = runner.invoke(app, ["export", str(target)])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert "agents_file" in data

    def test_export_json_flag_is_accepted(self, tmp_path):
        """Bug 1 regression guard: --json must be accepted without error."""
        _, target = _make_repo(tmp_path)
        result = runner.invoke(app, ["export", str(target), "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert "agents_file" in data

    def test_export_json_flag_output_same_as_without(self, tmp_path):
        """--json is a no-op: output must be identical with or without the flag."""
        _, target = _make_repo(tmp_path)
        result_plain = runner.invoke(app, ["export", str(target)])
        result_json = runner.invoke(app, ["export", str(target), "--json"])
        assert json.loads(result_plain.output) == json.loads(result_json.output)

    def test_export_empty_repo_exits_zero(self, tmp_path):
        """The hook uses '|| true' — export must not crash on a bare directory."""
        empty = tmp_path / "empty.py"
        empty.write_text("# empty\n")
        result = runner.invoke(app, ["export", str(empty)])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["agents_file"] is None

    def test_export_output_has_prompt_snippets(self, tmp_path):
        """SessionStart hook purpose: inject prompt_snippets into Claude context."""
        _, target = _make_repo(tmp_path)
        result = runner.invoke(app, ["export", str(target)])
        data = json.loads(result.output)
        assert isinstance(data["prompt_snippets"], list)
        assert len(data["prompt_snippets"]) >= 1


# ---------------------------------------------------------------------------
# TestCursorScriptLogic — tests Cursor .cursor/rules/*.mdc generation
# ---------------------------------------------------------------------------

class TestCursorScriptLogic:
    """Test the Cursor generation script logic against real export data."""

    def _generate(self, data: dict, rules_dir: Path) -> list[str]:
        """Run the Cursor generation logic inline, return list of created filenames."""
        rules_dir.mkdir(parents=True, exist_ok=True)
        generated = []

        if data.get("agents_file"):
            a = data["agents_file"]
            lines = ["---", "description: Project conventions and AI agent instructions",
                     "globs: ", "alwaysApply: true", "---", ""]
            if a.get("agent_instructions"):
                lines.append(a["agent_instructions"].rstrip())
                lines.append("")
            if a.get("conventions"):
                lines.append("## Conventions")
                for c in a["conventions"]:
                    lines.append(f"- {c}")
                lines.append("")
            if a.get("stack"):
                lines.append(f"## Stack\n{', '.join(a['stack'])}")
            (rules_dir / "project-context.mdc").write_text("\n".join(lines))
            generated.append("project-context.mdc")

        for rule in data.get("active_rules", []):
            globs = ", ".join(rule.get("applies_to", []))
            lines = ["---",
                     f"description: [{rule['severity'].upper()}] {rule['description']}",
                     f"globs: {globs}", "alwaysApply: false", "---", "",
                     f"# {rule['id']}", "", rule.get("description", "")]
            if rule.get("rationale"):
                lines.extend(["", f"**Rationale**: {rule['rationale']}"])
            fname = re.sub(r"[^a-z0-9-]", "-", rule["id"].lower()) + ".mdc"
            (rules_dir / fname).write_text("\n".join(lines))
            generated.append(fname)

        return generated

    def test_project_context_mdc_has_alwaysapply_true(self, tmp_path):
        _, target = _make_repo(tmp_path)
        data = export_context(resolve(target))
        rules_dir = tmp_path / "cursor_rules"
        self._generate(data, rules_dir)
        content = (rules_dir / "project-context.mdc").read_text()
        assert "alwaysApply: true" in content

    def test_project_context_includes_conventions(self, tmp_path):
        _, target = _make_repo(tmp_path)
        data = export_context(resolve(target))
        rules_dir = tmp_path / "cursor_rules"
        self._generate(data, rules_dir)
        content = (rules_dir / "project-context.mdc").read_text()
        assert "Use snake_case" in content

    def test_project_context_includes_agent_instructions(self, tmp_path):
        _, target = _make_repo(tmp_path)
        data = export_context(resolve(target))
        rules_dir = tmp_path / "cursor_rules"
        self._generate(data, rules_dir)
        content = (rules_dir / "project-context.mdc").read_text()
        assert "FastAPI assistant" in content

    def test_rule_mdc_globs_matches_applies_to(self, tmp_path):
        _, target = _make_repo(tmp_path)
        data = export_context(resolve(target))
        rules_dir = tmp_path / "cursor_rules"
        self._generate(data, rules_dir)
        rule_file = rules_dir / "no-raw-sql.mdc"
        assert rule_file.exists()
        content = rule_file.read_text()
        assert "**/*.py" in content
        assert "alwaysApply: false" in content

    def test_rule_filename_is_kebab_safe(self, tmp_path):
        """ID 'no-raw-sql' → 'no-raw-sql.mdc'."""
        _, target = _make_repo(tmp_path)
        data = export_context(resolve(target))
        rules_dir = tmp_path / "cursor_rules"
        generated = self._generate(data, rules_dir)
        assert "no-raw-sql.mdc" in generated

    def test_no_agents_file_skips_project_context(self, tmp_path):
        empty = tmp_path / "empty.py"
        empty.write_text("# empty\n")
        data = export_context(resolve(empty))
        rules_dir = tmp_path / "cursor_rules"
        generated = self._generate(data, rules_dir)
        assert "project-context.mdc" not in generated

    def test_script_runs_via_subprocess(self, tmp_path):
        """End-to-end: pipe agentmd export into the real script file."""
        _, target = _make_repo(tmp_path)
        export_result = subprocess.run(
            ["agentmd", "export", str(target)],
            capture_output=True, text=True,
        )
        assert export_result.returncode == 0
        script = OWN_ROOT / "scripts" / "generate-cursor-rules.py"
        gen_result = subprocess.run(
            [sys.executable, str(script)],
            input=export_result.stdout,
            capture_output=True, text=True,
            cwd=str(tmp_path),
        )
        assert gen_result.returncode == 0, gen_result.stderr
        assert "project-context.mdc" in gen_result.stdout
        assert (tmp_path / ".cursor" / "rules" / "project-context.mdc").exists()


# ---------------------------------------------------------------------------
# TestCopilotScriptLogic — tests Copilot instructions generation
# ---------------------------------------------------------------------------

class TestCopilotScriptLogic:
    """Test the Copilot instructions generation script."""

    def test_script_runs_via_subprocess(self, tmp_path):
        """End-to-end: pipe agentmd export into the real Copilot script."""
        _, target = _make_repo(tmp_path)
        export_result = subprocess.run(
            ["agentmd", "export", str(target)],
            capture_output=True, text=True,
        )
        assert export_result.returncode == 0
        script = OWN_ROOT / "scripts" / "generate-copilot-instructions.py"
        gen_result = subprocess.run(
            [sys.executable, str(script)],
            input=export_result.stdout,
            capture_output=True, text=True,
        )
        assert gen_result.returncode == 0, gen_result.stderr
        output = gen_result.stdout
        assert "FastAPI assistant" in output
        assert "Use snake_case" in output
        assert "no-raw-sql" in output

    def test_output_includes_rule_id_and_severity(self, tmp_path):
        _, target = _make_repo(tmp_path)
        export_result = subprocess.run(
            ["agentmd", "export", str(target)],
            capture_output=True, text=True,
        )
        script = OWN_ROOT / "scripts" / "generate-copilot-instructions.py"
        gen_result = subprocess.run(
            [sys.executable, str(script)],
            input=export_result.stdout, capture_output=True, text=True,
        )
        assert "[ERROR]" in gen_result.stdout
        assert "no-raw-sql" in gen_result.stdout


# ---------------------------------------------------------------------------
# TestWindsurfScriptLogic — tests Windsurf rules/workflows generation
# ---------------------------------------------------------------------------

class TestWindsurfScriptLogic:
    """Test the Windsurf rules and workflows generation script."""

    def test_script_runs_via_subprocess(self, tmp_path):
        """End-to-end: pipe agentmd export into the real Windsurf script."""
        _, target = _make_repo(tmp_path)
        export_result = subprocess.run(
            ["agentmd", "export", str(target)],
            capture_output=True, text=True,
        )
        assert export_result.returncode == 0
        script = OWN_ROOT / "scripts" / "generate-windsurf.py"
        gen_result = subprocess.run(
            [sys.executable, str(script)],
            input=export_result.stdout,
            capture_output=True, text=True,
            cwd=str(tmp_path),
        )
        assert gen_result.returncode == 0, gen_result.stderr
        assert (tmp_path / ".windsurf" / "rules" / "no-raw-sql.md").exists()
        assert (tmp_path / ".windsurf" / "workflows" / "my-skill.md").exists()

    def test_rule_has_trigger_and_glob(self, tmp_path):
        _, target = _make_repo(tmp_path)
        export_result = subprocess.run(
            ["agentmd", "export", str(target)],
            capture_output=True, text=True,
        )
        script = OWN_ROOT / "scripts" / "generate-windsurf.py"
        subprocess.run(
            [sys.executable, str(script)],
            input=export_result.stdout, capture_output=True, text=True, cwd=str(tmp_path),
        )
        content = (tmp_path / ".windsurf" / "rules" / "no-raw-sql.md").read_text()
        assert "trigger: glob" in content
        assert "**/*.py" in content

    def test_workflow_uses_skill_path_field(self, tmp_path):
        """Bug 2 fix: workflow file should include the skill's markdown body."""
        _, target = _make_repo(tmp_path)
        export_result = subprocess.run(
            ["agentmd", "export", str(target)],
            capture_output=True, text=True,
        )
        data = json.loads(export_result.stdout)
        # Confirm path field is present (Bug 2 regression guard)
        for skill in data["active_skills"]:
            assert skill.get("path") is not None, "Skill path is None — Bug 2 not fixed"
        script = OWN_ROOT / "scripts" / "generate-windsurf.py"
        subprocess.run(
            [sys.executable, str(script)],
            input=export_result.stdout, capture_output=True, text=True, cwd=str(tmp_path),
        )
        content = (tmp_path / ".windsurf" / "workflows" / "my-skill.md").read_text()
        # The skill's markdown body ("## Steps") should appear
        assert "Steps" in content


# ---------------------------------------------------------------------------
# TestOwnProjectAsFixture — uses the agentmd repo's own files
# ---------------------------------------------------------------------------

class TestOwnProjectAsFixture:
    """Use /home/user/agentmd itself as a real-world integration fixture."""

    def test_own_project_validates_cleanly(self):
        result = runner.invoke(app, ["validate", str(OWN_ROOT)])
        assert result.exit_code == 0, result.output

    def test_own_project_export_has_two_skills(self):
        target = OWN_ROOT / "agentmd" / "cli.py"
        data = export_context(resolve(target))
        skill_ids = {s["id"] for s in data["active_skills"]}
        assert "add-cli-command" in skill_ids
        assert "add-file-type" in skill_ids

    def test_own_project_skills_have_path(self):
        target = OWN_ROOT / "agentmd" / "cli.py"
        data = export_context(resolve(target))
        for skill in data["active_skills"]:
            assert skill["path"] is not None
            assert Path(skill["path"]).exists()

    def test_own_project_rules_apply_to_python_files(self):
        target = OWN_ROOT / "agentmd" / "cli.py"
        data = export_context(resolve(target))
        rule_ids = {r["id"] for r in data["active_rules"]}
        assert "no-print-statements" in rule_ids
        assert "type-hints-required" in rule_ids

    def test_own_project_prompt_snippets_include_trigger_and_path(self):
        target = OWN_ROOT / "agentmd" / "cli.py"
        data = export_context(resolve(target))
        for snippet in data["prompt_snippets"]:
            assert "Trigger:" in snippet
            assert ".skill.md" in snippet

    def test_own_project_export_cli_with_json_flag(self):
        """Smoke test: agentmd export cli.py --json works end-to-end."""
        result = runner.invoke(app, ["export", str(OWN_ROOT / "agentmd" / "cli.py"), "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["agents_file"]["name"] == "agentmd"

    def test_flat_fixture_export_correct_name(self):
        data = export_context(resolve(FLAT_FIXTURE / "AGENTS.md"))
        assert data["agents_file"]["name"] == "Flat Repo Example"

    def test_nested_fixture_backend_resolves_backend_agents(self):
        target = NESTED_FIXTURE / "backend" / "AGENTS.md"
        ctx = resolve(target)
        assert ctx.agents_file is not None
        assert ctx.agents_file.name == "Backend Package"
