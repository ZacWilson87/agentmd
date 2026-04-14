---
agentmd: "1.0"
type: agents
scope: package
name: "Backend Package"
stack:
  - python
  - fastapi
  - postgresql
conventions:
  - "Use snake_case for all identifiers"
  - "Type hints required on all functions"
skills:
  - skills/scaffold-endpoint.skill.md
rules:
  - rules/no-raw-sql.rule.md
agent_instructions: |
  You are in the FastAPI backend package.
  All database access goes through the ORM.
  Never write raw SQL.
---

# Backend Package

FastAPI + SQLAlchemy backend.
