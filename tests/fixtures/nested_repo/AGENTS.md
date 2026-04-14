---
agentmd: "1.0"
type: agents
scope: project
name: "Nested Repo Example"
stack:
  - python
  - fastapi
  - react
  - postgresql
conventions:
  - "Use snake_case for Python, camelCase for TypeScript"
  - "All API responses use camelCase JSON"
  - "No print() statements — use structlog"
skills:
  - skills/write-test.skill.md
rules:
  - rules/no-todo-comments.rule.md
agent_instructions: |
  You are operating in a full-stack monorepo.
  The backend is FastAPI, the frontend is React.
  Never modify files in /generated.
---

# Nested Repo Example

A monorepo demonstrating nested agentmd scoping.
