---
agentmd: "1.0"
type: skill
id: scaffold-endpoint
version: "2.0"
description: "Scaffold a FastAPI endpoint with Pydantic schema and tests"
trigger: "when asked to create a new API endpoint"
inputs:
  - name: resource_name
    type: string
    required: true
  - name: method
    type: enum
    values: [GET, POST, PUT, DELETE]
    default: GET
outputs:
  - "backend/api/{resource_name}/router.py"
  - "backend/api/{resource_name}/schemas.py"
  - "backend/tests/test_{resource_name}.py"
tags:
  - backend
  - fastapi
  - scaffold
---

## Steps

1. Create the router file with the endpoint definition.
2. Create the Pydantic schemas file.
3. Register the router in `backend/api/__init__.py`.
4. Write pytest tests.
