"""Pydantic v2 models for all three agentmd file types."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator


class AgentsFile(BaseModel):
    """Model for AGENTS.md files."""

    agentmd: str = Field(..., description="Spec version — must be '1.0'.")
    type: Literal["agents"]
    scope: Literal["project", "package", "module"] = "project"
    name: str
    stack: list[str] = []
    conventions: list[str] = []
    skills: list[str] = []  # relative file paths to SKILL.md files
    rules: list[str] = []   # relative file paths to RULE.md files
    agent_instructions: str = ""

    @field_validator("agentmd")
    @classmethod
    def validate_spec_version(cls, v: str) -> str:
        if v != "1.0":
            raise ValueError(f"agentmd spec version must be '1.0', got '{v}'")
        return v


class SkillInput(BaseModel):
    """A single input parameter for a skill."""

    name: str
    type: str  # string | enum | boolean | integer
    required: bool = True
    values: list[str] = []  # for enum type
    default: str | None = None
    description: str = ""


class SkillFile(BaseModel):
    """Model for *.skill.md files."""

    agentmd: str = Field(..., description="Spec version — must be '1.0'.")
    type: Literal["skill"]
    id: str = Field(..., description="Kebab-case unique identifier.")
    version: str
    description: str
    trigger: str
    inputs: list[SkillInput] = []
    outputs: list[str] = []
    tags: list[str] = []

    @field_validator("agentmd")
    @classmethod
    def validate_spec_version(cls, v: str) -> str:
        if v != "1.0":
            raise ValueError(f"agentmd spec version must be '1.0', got '{v}'")
        return v

    @field_validator("id")
    @classmethod
    def validate_kebab_case(cls, v: str) -> str:
        import re
        if not re.match(r"^[a-z0-9]+(-[a-z0-9]+)*$", v):
            raise ValueError(f"Skill id must be kebab-case (lowercase letters, digits, hyphens), got '{v}'")
        return v


class RuleFile(BaseModel):
    """Model for *.rule.md files."""

    agentmd: str = Field(..., description="Spec version — must be '1.0'.")
    type: Literal["rule"]
    id: str = Field(..., description="Kebab-case unique identifier.")
    severity: Literal["error", "warning", "info"]
    description: str
    rationale: str = ""
    applies_to: list[str] = ["**/*"]
    exceptions: list[str] = []

    @field_validator("agentmd")
    @classmethod
    def validate_spec_version(cls, v: str) -> str:
        if v != "1.0":
            raise ValueError(f"agentmd spec version must be '1.0', got '{v}'")
        return v

    @field_validator("id")
    @classmethod
    def validate_kebab_case(cls, v: str) -> str:
        import re
        if not re.match(r"^[a-z0-9]+(-[a-z0-9]+)*$", v):
            raise ValueError(f"Rule id must be kebab-case (lowercase letters, digits, hyphens), got '{v}'")
        return v


# Union type for any parsed agentmd file
AgentMDFile = AgentsFile | SkillFile | RuleFile
