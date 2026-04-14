---
agentmd: "1.0"
type: skill
id: add-cli-command
version: "1.0"
description: "Add a new command to the agentmd CLI"
trigger: "when asked to add a new CLI command"
inputs:
  - name: command_name
    type: string
    required: true
    description: "The CLI command name (e.g. 'check', 'diff')"
  - name: description
    type: string
    required: true
    description: "One-line description of what the command does"
outputs:
  - "agentmd/cli.py (modified)"
  - "tests/test_cli.py (modified)"
tags:
  - cli
  - development
---

## Steps

1. Add the command function to `agentmd/cli.py` decorated with `@app.command()`.
2. Use `typer.Argument` for required positional args, `typer.Option` for flags.
3. Use `rich` console for output — never `print()`.
4. Add a test class in `tests/test_cli.py` using `CliRunner` from `typer.testing`.
5. Ensure the command appears in `agentmd --help` output.

## Notes

- Sub-command groups (like `list`, `add`) use `typer.Typer()` with `app.add_typer()`.
- Error output goes to `err_console` (stderr), normal output to `console` (stdout).
- Commands that fail should call `raise typer.Exit(1)`.
