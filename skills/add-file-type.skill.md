---
agentmd: "1.0"
type: skill
id: add-file-type
version: "1.0"
description: "Add a new agentmd file type to the standard"
trigger: "when asked to add a new file type to the agentmd spec"
inputs:
  - name: type_name
    type: string
    required: true
    description: "The type identifier (e.g. 'workflow')"
  - name: file_suffix
    type: string
    required: true
    description: "File suffix convention (e.g. '.workflow.md')"
outputs:
  - "agentmd/models.py (new model class)"
  - "agentmd/parser.py (updated _file_type, model_map)"
  - "agentmd/templates/<type_name>.md.jinja"
  - "docs/spec.md (updated)"
tags:
  - development
  - spec
---

## Steps

1. Add a new Pydantic model class in `agentmd/models.py` inheriting from `BaseModel`.
   - Include `agentmd: str`, `type: Literal["<type_name>"]`, and all required fields.
   - Add `@field_validator("agentmd")` for spec version check.
   - Update the `AgentMDFile` union type at the bottom of the file.

2. Update `agentmd/parser.py`:
   - Add the new suffix to `_file_type()`.
   - Add the new type to `model_map` in `parse_file()`.

3. Create `agentmd/templates/<type_name>.md.jinja` with a useful default template.

4. Update `docs/spec.md` with the new file type's schema table and description.

5. Add tests in `tests/test_models.py` and `tests/test_parser.py`.

## Notes

- Keep the type name consistent: filename suffix, `type` field, and model class name.
- Follow the same YAML frontmatter + Markdown body convention as existing types.
