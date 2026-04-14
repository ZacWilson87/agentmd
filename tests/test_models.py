"""Tests for agentmd Pydantic models."""

import pytest
from pydantic import ValidationError

from agentmd.models import AgentsFile, RuleFile, SkillFile, SkillInput


class TestAgentsFile:
    def test_valid_minimal(self):
        a = AgentsFile.model_validate({
            "agentmd": "1.0",
            "type": "agents",
            "name": "My Project",
        })
        assert a.name == "My Project"
        assert a.scope == "project"
        assert a.stack == []
        assert a.skills == []

    def test_valid_full(self):
        a = AgentsFile.model_validate({
            "agentmd": "1.0",
            "type": "agents",
            "scope": "package",
            "name": "Backend",
            "stack": ["python", "fastapi"],
            "conventions": ["snake_case identifiers"],
            "skills": ["skills/scaffold.skill.md"],
            "rules": ["rules/no-raw-sql.rule.md"],
            "agent_instructions": "Be careful with migrations.",
        })
        assert a.stack == ["python", "fastapi"]
        assert len(a.skills) == 1

    def test_wrong_spec_version(self):
        with pytest.raises(ValidationError, match="spec version must be '1.0'"):
            AgentsFile.model_validate({
                "agentmd": "2.0",
                "type": "agents",
                "name": "X",
            })

    def test_missing_name(self):
        with pytest.raises(ValidationError):
            AgentsFile.model_validate({
                "agentmd": "1.0",
                "type": "agents",
            })

    def test_invalid_scope(self):
        with pytest.raises(ValidationError):
            AgentsFile.model_validate({
                "agentmd": "1.0",
                "type": "agents",
                "name": "X",
                "scope": "global",
            })


class TestSkillFile:
    def test_valid_minimal(self):
        s = SkillFile.model_validate({
            "agentmd": "1.0",
            "type": "skill",
            "id": "scaffold-component",
            "version": "1.0",
            "description": "Scaffold a React component",
            "trigger": "when asked to create a component",
        })
        assert s.id == "scaffold-component"
        assert s.tags == []

    def test_valid_with_inputs(self):
        s = SkillFile.model_validate({
            "agentmd": "1.0",
            "type": "skill",
            "id": "write-test",
            "version": "2.1",
            "description": "Write a test",
            "trigger": "write test for",
            "inputs": [
                {"name": "target", "type": "string", "required": True},
                {"name": "style", "type": "enum", "values": ["unit", "integration"], "default": "unit"},
            ],
            "outputs": ["tests/test_{target}.py"],
            "tags": ["testing", "python"],
        })
        assert len(s.inputs) == 2
        assert s.inputs[1].values == ["unit", "integration"]

    def test_invalid_id_not_kebab(self):
        with pytest.raises(ValidationError, match="kebab-case"):
            SkillFile.model_validate({
                "agentmd": "1.0",
                "type": "skill",
                "id": "ScaffoldComponent",
                "version": "1.0",
                "description": "x",
                "trigger": "x",
            })

    def test_invalid_id_spaces(self):
        with pytest.raises(ValidationError, match="kebab-case"):
            SkillFile.model_validate({
                "agentmd": "1.0",
                "type": "skill",
                "id": "scaffold component",
                "version": "1.0",
                "description": "x",
                "trigger": "x",
            })


class TestRuleFile:
    def test_valid_minimal(self):
        r = RuleFile.model_validate({
            "agentmd": "1.0",
            "type": "rule",
            "id": "no-raw-sql",
            "severity": "error",
            "description": "No raw SQL",
        })
        assert r.applies_to == ["**/*"]
        assert r.exceptions == []

    def test_valid_full(self):
        r = RuleFile.model_validate({
            "agentmd": "1.0",
            "type": "rule",
            "id": "type-hints-required",
            "severity": "warning",
            "description": "All functions need type hints",
            "rationale": "Improves IDE support",
            "applies_to": ["**/*.py"],
            "exceptions": ["migrations/**", "scripts/seed_*.py"],
        })
        assert r.rationale == "Improves IDE support"
        assert len(r.exceptions) == 2

    def test_invalid_severity(self):
        with pytest.raises(ValidationError):
            RuleFile.model_validate({
                "agentmd": "1.0",
                "type": "rule",
                "id": "my-rule",
                "severity": "critical",
                "description": "x",
            })

    def test_invalid_id_underscore(self):
        with pytest.raises(ValidationError, match="kebab-case"):
            RuleFile.model_validate({
                "agentmd": "1.0",
                "type": "rule",
                "id": "no_raw_sql",
                "severity": "error",
                "description": "x",
            })
