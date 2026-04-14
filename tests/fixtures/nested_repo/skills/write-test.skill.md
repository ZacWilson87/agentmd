---
agentmd: "1.0"
type: skill
id: write-test
version: "1.0"
description: "Write a comprehensive test for a given module"
trigger: "when asked to write tests for"
inputs:
  - name: module_path
    type: string
    required: true
outputs:
  - "tests/test_{module_name}.py"
tags:
  - testing
---

## Steps

1. Identify the public interface of the module.
2. Write unit tests for each function/method.
3. Add edge cases and error path tests.
