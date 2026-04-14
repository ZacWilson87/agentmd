"""Tests for YAML frontmatter extraction and file parsing."""

import pytest
from pathlib import Path

from agentmd.parser import ParseError, extract_frontmatter, parse_file
from agentmd.models import AgentsFile, SkillFile, RuleFile


VALID_AGENTS = """\
---
agentmd: "1.0"
type: agents
name: "Test Project"
scope: project
stack:
  - python
conventions:
  - "snake_case"
---

# Test Project

Some narrative.
"""

VALID_SKILL = """\
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

1. Do thing.
"""

VALID_RULE = """\
---
agentmd: "1.0"
type: rule
id: no-raw-sql
severity: error
description: "No raw SQL"
rationale: "Prevents injection"
applies_to:
  - "**/*.py"
---

## Rule

Never use raw SQL.
"""


class TestExtractFrontmatter:
    def test_valid(self):
        data, body = extract_frontmatter(VALID_AGENTS)
        assert data["agentmd"] == "1.0"
        assert data["name"] == "Test Project"
        assert "Test Project" in body

    def test_no_frontmatter(self):
        with pytest.raises(ParseError, match="No valid YAML frontmatter"):
            extract_frontmatter("# Just a title\n\nSome text.")

    def test_unclosed_frontmatter(self):
        with pytest.raises(ParseError, match="No valid YAML frontmatter"):
            extract_frontmatter("---\nagentmd: '1.0'\nname: X\n")

    def test_invalid_yaml(self):
        with pytest.raises(ParseError, match="YAML parse error"):
            extract_frontmatter("---\n: invalid: yaml: here\n---\n")

    def test_non_dict_yaml(self):
        with pytest.raises(ParseError, match="must be a YAML mapping"):
            extract_frontmatter("---\n- item1\n- item2\n---\n")


class TestParseFile:
    def test_parse_agents(self, tmp_path):
        f = tmp_path / "AGENTS.md"
        f.write_text(VALID_AGENTS)
        result = parse_file(f)
        assert isinstance(result, AgentsFile)
        assert result.name == "Test Project"

    def test_parse_skill(self, tmp_path):
        f = tmp_path / "scaffold-component.skill.md"
        f.write_text(VALID_SKILL)
        result = parse_file(f)
        assert isinstance(result, SkillFile)
        assert result.id == "scaffold-component"

    def test_parse_rule(self, tmp_path):
        f = tmp_path / "no-raw-sql.rule.md"
        f.write_text(VALID_RULE)
        result = parse_file(f)
        assert isinstance(result, RuleFile)
        assert result.severity == "error"

    def test_missing_file(self, tmp_path):
        with pytest.raises(ParseError, match="File not found"):
            parse_file(tmp_path / "nonexistent.md")

    def test_validation_error_bad_version(self, tmp_path):
        f = tmp_path / "AGENTS.md"
        f.write_text("---\nagentmd: '2.0'\ntype: agents\nname: X\n---\n")
        with pytest.raises(ParseError, match="validation failed"):
            parse_file(f)

    def test_type_mismatch(self, tmp_path):
        # File named as skill but declares type: agents
        f = tmp_path / "foo.skill.md"
        f.write_text("---\nagentmd: '1.0'\ntype: agents\nname: X\n---\n")
        with pytest.raises(ParseError, match="filename implies type 'skill'"):
            parse_file(f)

    def test_invalid_skill_id(self, tmp_path):
        f = tmp_path / "my_skill.skill.md"
        f.write_text(
            "---\nagentmd: '1.0'\ntype: skill\nid: my_skill\nversion: '1.0'\n"
            "description: x\ntrigger: x\n---\n"
        )
        with pytest.raises(ParseError, match="validation failed"):
            parse_file(f)
