---
agentmd: "1.0"
type: agents
scope: project
name: "Flat Repo Example"
stack:
  - python
  - fastapi
conventions:
  - "Use snake_case for all Python identifiers"
  - "No print() statements — use structlog"
skills:
  - skills/scaffold-endpoint.skill.md
rules:
  - rules/no-raw-sql.rule.md
agent_instructions: |
  You are operating in a simple FastAPI project.
  Always check SKILL.md files before implementing features.
---

# Flat Repo Example

A simple example repository demonstrating agentmd in a flat structure.
