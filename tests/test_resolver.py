"""Tests for the scope resolution algorithm."""

import pytest
from pathlib import Path

from agentmd.resolver import resolve, ResolvedContext


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


AGENTS_CONTENT = """\
---
agentmd: "1.0"
type: agents
name: "Test Project"
scope: project
stack:
  - python
---
"""

SKILL_CONTENT = """\
---
agentmd: "1.0"
type: skill
id: scaffold-component
version: "1.0"
description: "Scaffold a component"
trigger: "when asked to scaffold"
---
"""

RULE_PY_CONTENT = """\
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

RULE_ALL_CONTENT = """\
---
agentmd: "1.0"
type: rule
id: no-todo-comments
severity: warning
description: "No TODO comments"
applies_to:
  - "**/*"
---
"""


class TestFlatRepo:
    """Tests against a simple flat repo structure."""

    def test_resolves_agents(self, tmp_path):
        _write(tmp_path / "AGENTS.md", AGENTS_CONTENT)
        target = tmp_path / "src" / "main.py"
        target.parent.mkdir()
        target.touch()
        ctx = resolve(target)
        assert ctx.agents_file is not None
        assert ctx.agents_file.name == "Test Project"

    def test_resolves_skill_in_skills_dir(self, tmp_path):
        _write(tmp_path / "AGENTS.md", AGENTS_CONTENT)
        _write(tmp_path / "skills" / "scaffold-component.skill.md", SKILL_CONTENT)
        target = tmp_path / "src" / "main.py"
        target.parent.mkdir()
        target.touch()
        ctx = resolve(target)
        assert len(ctx.active_skills) == 1
        assert ctx.active_skills[0].id == "scaffold-component"

    def test_rule_filtered_by_applies_to(self, tmp_path):
        _write(tmp_path / "AGENTS.md", AGENTS_CONTENT)
        _write(tmp_path / "rules" / "no-raw-sql.rule.md", RULE_PY_CONTENT)
        py_file = tmp_path / "src" / "app.py"
        py_file.parent.mkdir()
        py_file.touch()
        js_file = tmp_path / "src" / "app.js"
        js_file.touch()

        py_ctx = resolve(py_file)
        js_ctx = resolve(js_file)

        assert any(r.id == "no-raw-sql" for r in py_ctx.active_rules)
        assert not any(r.id == "no-raw-sql" for r in js_ctx.active_rules)

    def test_no_agents_md(self, tmp_path):
        target = tmp_path / "src" / "main.py"
        target.parent.mkdir()
        target.touch()
        ctx = resolve(target)
        assert ctx.agents_file is None


class TestNestedRepo:
    """Tests against a nested repo: project root + subdirectory with own rules."""

    def test_closest_agents_wins(self, tmp_path):
        _write(tmp_path / "AGENTS.md", AGENTS_CONTENT)
        nested_agents = """\
---
agentmd: "1.0"
type: agents
name: "Backend Package"
scope: package
---
"""
        _write(tmp_path / "backend" / "AGENTS.md", nested_agents)
        target = tmp_path / "backend" / "api" / "views.py"
        target.parent.mkdir(parents=True)
        target.touch()
        ctx = resolve(target)
        # Should pick up the nearest AGENTS.md (backend/)
        assert ctx.agents_file.name == "Backend Package"

    def test_rules_accumulate_from_parent(self, tmp_path):
        _write(tmp_path / "AGENTS.md", AGENTS_CONTENT)
        _write(tmp_path / "rules" / "no-todo-comments.rule.md", RULE_ALL_CONTENT)
        _write(tmp_path / "rules" / "no-raw-sql.rule.md", RULE_PY_CONTENT)
        target = tmp_path / "backend" / "app.py"
        target.parent.mkdir()
        target.touch()
        ctx = resolve(target)
        rule_ids = {r.id for r in ctx.active_rules}
        assert "no-todo-comments" in rule_ids
        assert "no-raw-sql" in rule_ids

    def test_skills_accumulate_across_scopes(self, tmp_path):
        _write(tmp_path / "AGENTS.md", AGENTS_CONTENT)
        _write(tmp_path / "skills" / "scaffold-component.skill.md", SKILL_CONTENT)
        local_skill = """\
---
agentmd: "1.0"
type: skill
id: write-test
version: "1.0"
description: "Write a test"
trigger: "write test for"
---
"""
        _write(tmp_path / "backend" / "skills" / "write-test.skill.md", local_skill)
        target = tmp_path / "backend" / "app.py"
        target.parent.mkdir(exist_ok=True)
        target.touch()
        ctx = resolve(target)
        skill_ids = {s.id for s in ctx.active_skills}
        # Both root and nested skills collected
        assert "scaffold-component" in skill_ids
        assert "write-test" in skill_ids

    def test_no_duplicate_rules(self, tmp_path):
        _write(tmp_path / "AGENTS.md", AGENTS_CONTENT)
        _write(tmp_path / "rules" / "no-raw-sql.rule.md", RULE_PY_CONTENT)
        # Same rule in subdirectory — should not appear twice
        _write(tmp_path / "backend" / "rules" / "no-raw-sql.rule.md", RULE_PY_CONTENT)
        target = tmp_path / "backend" / "app.py"
        target.parent.mkdir(exist_ok=True)
        target.touch()
        ctx = resolve(target)
        ids = [r.id for r in ctx.active_rules]
        assert ids.count("no-raw-sql") == 1


class TestReferencedFiles:
    """Test explicit skills/rules references in AGENTS.md."""

    def test_referenced_skill_loaded(self, tmp_path):
        skill_path = tmp_path / "skills" / "scaffold-component.skill.md"
        _write(skill_path, SKILL_CONTENT)
        agents = f"""\
---
agentmd: "1.0"
type: agents
name: "My Project"
skills:
  - skills/scaffold-component.skill.md
---
"""
        _write(tmp_path / "AGENTS.md", agents)
        target = tmp_path / "src" / "main.py"
        target.parent.mkdir()
        target.touch()
        ctx = resolve(target)
        assert any(s.id == "scaffold-component" for s in ctx.active_skills)

    def test_missing_referenced_skill_skipped(self, tmp_path):
        agents = """\
---
agentmd: "1.0"
type: agents
name: "My Project"
skills:
  - skills/nonexistent.skill.md
---
"""
        _write(tmp_path / "AGENTS.md", agents)
        target = tmp_path / "src" / "main.py"
        target.parent.mkdir()
        target.touch()
        # Should not raise, just silently skip
        ctx = resolve(target)
        assert ctx.active_skills == []


class TestPromptSnippets:
    """Tests for the prompt_snippets feature."""

    def test_skill_generates_snippet(self, tmp_path):
        _write(tmp_path / "AGENTS.md", AGENTS_CONTENT)
        _write(tmp_path / "skills" / "scaffold-component.skill.md", SKILL_CONTENT)
        target = tmp_path / "src" / "main.py"
        target.parent.mkdir()
        target.touch()
        ctx = resolve(target)
        assert len(ctx.prompt_snippets) == 1
        snippet = ctx.prompt_snippets[0]
        assert "[scaffold-component]" in snippet
        assert "when asked to scaffold" in snippet  # trigger value
        assert "Trigger:" in snippet

    def test_snippet_includes_file_path(self, tmp_path):
        _write(tmp_path / "AGENTS.md", AGENTS_CONTENT)
        skill_path = tmp_path / "skills" / "scaffold-component.skill.md"
        _write(skill_path, SKILL_CONTENT)
        target = tmp_path / "src" / "main.py"
        target.parent.mkdir()
        target.touch()
        ctx = resolve(target)
        assert str(skill_path) in ctx.prompt_snippets[0]

    def test_multiple_skills_multiple_snippets(self, tmp_path):
        _write(tmp_path / "AGENTS.md", AGENTS_CONTENT)
        _write(tmp_path / "skills" / "scaffold-component.skill.md", SKILL_CONTENT)
        extra_skill = """\
---
agentmd: "1.0"
type: skill
id: write-test
version: "1.0"
description: "Write a test"
trigger: "write a test for"
---
"""
        _write(tmp_path / "skills" / "write-test.skill.md", extra_skill)
        target = tmp_path / "src" / "main.py"
        target.parent.mkdir()
        target.touch()
        ctx = resolve(target)
        assert len(ctx.prompt_snippets) == 2
        ids_in_snippets = {s.id for s in ctx.active_skills}
        assert "scaffold-component" in ids_in_snippets
        assert "write-test" in ids_in_snippets

    def test_no_skills_no_snippets(self, tmp_path):
        _write(tmp_path / "AGENTS.md", AGENTS_CONTENT)
        target = tmp_path / "src" / "main.py"
        target.parent.mkdir()
        target.touch()
        ctx = resolve(target)
        assert ctx.prompt_snippets == []

    def test_skill_paths_populated(self, tmp_path):
        _write(tmp_path / "AGENTS.md", AGENTS_CONTENT)
        skill_path = tmp_path / "skills" / "scaffold-component.skill.md"
        _write(skill_path, SKILL_CONTENT)
        target = tmp_path / "src" / "main.py"
        target.parent.mkdir()
        target.touch()
        ctx = resolve(target)
        assert "scaffold-component" in ctx.skill_paths
        assert ctx.skill_paths["scaffold-component"] == skill_path


class TestCircularDependencyGuard:
    """Tests for duplicate/circular skill reference detection."""

    def test_duplicate_skill_path_in_agents_md_emits_warning(self, tmp_path):
        skill_path = tmp_path / "skills" / "scaffold-component.skill.md"
        _write(skill_path, SKILL_CONTENT)
        # Reference the same path twice in the skills list
        agents = """\
---
agentmd: "1.0"
type: agents
name: "My Project"
skills:
  - skills/scaffold-component.skill.md
  - skills/scaffold-component.skill.md
---
"""
        _write(tmp_path / "AGENTS.md", agents)
        target = tmp_path / "src" / "main.py"
        target.parent.mkdir()
        target.touch()
        ctx = resolve(target)
        # Skill should be loaded exactly once
        skill_ids = [s.id for s in ctx.active_skills]
        assert skill_ids.count("scaffold-component") == 1
        # Warning should be recorded
        assert any("Duplicate skill reference" in w for w in ctx.warnings)

    def test_duplicate_skill_path_not_fatal(self, tmp_path):
        skill_path = tmp_path / "skills" / "scaffold-component.skill.md"
        _write(skill_path, SKILL_CONTENT)
        agents = """\
---
agentmd: "1.0"
type: agents
name: "My Project"
skills:
  - skills/scaffold-component.skill.md
  - skills/scaffold-component.skill.md
---
"""
        _write(tmp_path / "AGENTS.md", agents)
        target = tmp_path / "src" / "main.py"
        target.parent.mkdir()
        target.touch()
        # Must not raise
        ctx = resolve(target)
        assert ctx.agents_file is not None


class TestWarnings:
    """Tests for non-fatal warnings collected during resolution."""

    def test_broken_agents_md_emits_warning(self, tmp_path):
        # Write an AGENTS.md with broken YAML
        broken = "---\nnot: valid: yaml: [unclosed\n---\n"
        _write(tmp_path / "AGENTS.md", broken)
        target = tmp_path / "main.py"
        target.touch()
        ctx = resolve(target)
        # Should not raise; broken file produces a warning
        assert any("AGENTS.md" in w or "unreadable" in w for w in ctx.warnings)

    def test_no_warnings_on_clean_repo(self, tmp_path):
        _write(tmp_path / "AGENTS.md", AGENTS_CONTENT)
        _write(tmp_path / "skills" / "scaffold-component.skill.md", SKILL_CONTENT)
        target = tmp_path / "src" / "main.py"
        target.parent.mkdir()
        target.touch()
        ctx = resolve(target)
        assert ctx.warnings == []

    def test_broken_rule_md_emits_no_warning_but_is_skipped(self, tmp_path):
        """Broken rule files in rules/ dir are silently skipped (not warned).

        The conservative policy: resolution skips broken files; validate reports them.
        """
        _write(tmp_path / "AGENTS.md", AGENTS_CONTENT)
        _write(tmp_path / "rules" / "bad.rule.md", "---\nnot: valid: yaml: [unclosed\n---\n")
        target = tmp_path / "main.py"
        target.touch()
        # Should not raise, broken rule is skipped
        ctx = resolve(target)
        assert ctx.active_rules == []
