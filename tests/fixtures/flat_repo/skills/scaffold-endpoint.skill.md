---
agentmd: "1.0"
type: skill
id: scaffold-endpoint
version: "1.0"
description: "Scaffold a new FastAPI endpoint with tests"
trigger: "when asked to create a new API endpoint"
inputs:
  - name: endpoint_name
    type: string
    required: true
  - name: method
    type: enum
    values: [GET, POST, PUT, DELETE, PATCH]
    default: GET
outputs:
  - "api/{endpoint_name}.py"
  - "tests/test_{endpoint_name}.py"
tags:
  - backend
  - fastapi
  - scaffold
---

## Steps

1. Create the endpoint file in `api/`.
2. Add route registration in `api/__init__.py`.
3. Create the test file using pytest.
