---
agentmd: "1.0"
type: agents
scope: package
name: "Frontend Package"
stack:
  - react
  - typescript
  - vite
conventions:
  - "Use camelCase for all TypeScript identifiers"
  - "Components use PascalCase"
  - "No console.log() in committed code"
skills:
  - skills/scaffold-component.skill.md
rules:
  - rules/no-console-log.rule.md
agent_instructions: |
  You are in the React + TypeScript frontend package.
  All components must have TypeScript types.
  Use React Testing Library for tests.
---

# Frontend Package

React + TypeScript + Vite frontend.
