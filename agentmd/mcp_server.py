"""Minimal MCP (Model Context Protocol) server for agentmd.

Implements JSON-RPC 2.0 over stdio — the standard transport for local MCP
servers consumed by Claude Code and other agents.

Protocol flow:
  client → initialize         server responds with capabilities
  client → notifications/initialized   (no response)
  client → tools/list         server lists available tools
  client → tools/call         server executes a tool and returns result

Run with:  agentmd mcp [--root PATH]
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path
from typing import Any

from agentmd import __version__

# MCP protocol version this server implements
_PROTOCOL_VERSION = "2024-11-05"

# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOLS: list[dict[str, Any]] = [
    {
        "name": "agentmd_resolve",
        "description": (
            "Resolve agentmd context (AGENTS.md, active skills, active rules) "
            "for a given file path. Returns structured JSON."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute or relative path to the target file.",
                }
            },
            "required": ["path"],
        },
    },
    {
        "name": "agentmd_list_skills",
        "description": "List all SKILL.md files discovered under the repo root.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "root": {
                    "type": "string",
                    "description": "Repo root directory. Defaults to CWD.",
                }
            },
        },
    },
    {
        "name": "agentmd_list_rules",
        "description": "List all RULE.md files discovered under the repo root.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "root": {
                    "type": "string",
                    "description": "Repo root directory. Defaults to CWD.",
                }
            },
        },
    },
    {
        "name": "agentmd_validate",
        "description": "Validate all agentmd files in the repo. Returns pass/fail per file.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "root": {
                    "type": "string",
                    "description": "Repo root directory. Defaults to CWD.",
                }
            },
        },
    },
    {
        "name": "agentmd_check",
        "description": (
            "Check a file for rule violations using AST and pattern analysis. "
            "Returns violations grouped by rule ID with line numbers."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file to check.",
                }
            },
            "required": ["path"],
        },
    },
    {
        "name": "agentmd_audit",
        "description": (
            "Run a full audit: validate files, check rules across all matching "
            "files, detect context drift, and verify SKILL.md trust state."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "root": {
                    "type": "string",
                    "description": "Repo root directory. Defaults to CWD.",
                }
            },
        },
    },
]


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------


def _handle_resolve(args: dict[str, Any]) -> Any:
    from agentmd.resolver import resolve
    from agentmd.exporter import export_context

    path = Path(args["path"])
    ctx = resolve(path)
    return export_context(ctx)


def _handle_list_skills(args: dict[str, Any]) -> Any:
    from agentmd.parser import find_all_agentmd_files, parse_file
    from agentmd.models import SkillFile

    root = Path(args.get("root", "."))
    skills = []
    for fpath in find_all_agentmd_files(root):
        try:
            parsed = parse_file(fpath)
            if isinstance(parsed, SkillFile):
                skills.append(
                    {
                        "id": parsed.id,
                        "version": parsed.version,
                        "description": parsed.description,
                        "trigger": parsed.trigger,
                        "tags": parsed.tags,
                        "path": str(fpath),
                    }
                )
        except Exception:
            pass
    return skills


def _handle_list_rules(args: dict[str, Any]) -> Any:
    from agentmd.parser import find_all_agentmd_files, parse_file
    from agentmd.models import RuleFile

    root = Path(args.get("root", "."))
    rules = []
    for fpath in find_all_agentmd_files(root):
        try:
            parsed = parse_file(fpath)
            if isinstance(parsed, RuleFile):
                rules.append(
                    {
                        "id": parsed.id,
                        "severity": parsed.severity,
                        "description": parsed.description,
                        "applies_to": parsed.applies_to,
                        "exceptions": parsed.exceptions,
                        "immutable": parsed.immutable,
                        "path": str(fpath),
                    }
                )
        except Exception:
            pass
    return rules


def _handle_validate(args: dict[str, Any]) -> Any:
    from agentmd.parser import find_all_agentmd_files, parse_file, ParseError

    root = Path(args.get("root", "."))
    results = []
    for fpath in find_all_agentmd_files(root):
        try:
            parse_file(fpath)
            results.append({"path": str(fpath), "valid": True, "error": None})
        except ParseError as exc:
            results.append({"path": str(fpath), "valid": False, "error": str(exc)})
    return results


def _handle_check(args: dict[str, Any]) -> Any:
    from agentmd.resolver import resolve
    from agentmd.checker import check_file

    path = Path(args["path"])
    ctx = resolve(path)
    violations = check_file(path, ctx)
    return {
        "path": str(path),
        "violations": {
            rule_id: [
                {"message": v.message, "line": v.line} for v in vs
            ]
            for rule_id, vs in violations.items()
        },
    }


def _handle_audit(args: dict[str, Any]) -> Any:
    from agentmd.auditor import run_audit

    root = Path(args.get("root", "."))
    report = run_audit(root)
    return report.to_dict()


_HANDLERS: dict[str, Any] = {
    "agentmd_resolve": _handle_resolve,
    "agentmd_list_skills": _handle_list_skills,
    "agentmd_list_rules": _handle_list_rules,
    "agentmd_validate": _handle_validate,
    "agentmd_check": _handle_check,
    "agentmd_audit": _handle_audit,
}


# ---------------------------------------------------------------------------
# JSON-RPC dispatch
# ---------------------------------------------------------------------------


def _ok(id_: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "result": result}


def _error(id_: Any, code: int, message: str, data: Any = None) -> dict:
    err: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": id_, "error": err}


def _dispatch(msg: dict) -> dict | None:
    method: str = msg.get("method", "")
    id_: Any = msg.get("id")
    params: dict = msg.get("params") or {}

    # Notifications have no id — respond with nothing
    if id_ is None and method.startswith("notifications/"):
        return None

    if method == "initialize":
        return _ok(
            id_,
            {
                "protocolVersion": _PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "agentmd", "version": __version__},
            },
        )

    if method == "tools/list":
        return _ok(id_, {"tools": TOOLS})

    if method == "tools/call":
        tool_name: str = params.get("name", "")
        arguments: dict = params.get("arguments") or {}
        handler = _HANDLERS.get(tool_name)
        if handler is None:
            return _error(id_, -32601, f"Unknown tool: {tool_name}")
        try:
            result = handler(arguments)
            return _ok(
                id_,
                {
                    "content": [
                        {"type": "text", "text": json.dumps(result, indent=2)}
                    ]
                },
            )
        except Exception as exc:
            return _error(
                id_,
                -32603,
                f"Tool execution error: {exc}",
                traceback.format_exc(),
            )

    if method == "ping":
        return _ok(id_, {})

    # Unknown method
    return _error(id_, -32601, f"Method not found: {method}")


# ---------------------------------------------------------------------------
# Main server loop
# ---------------------------------------------------------------------------


def run_server(root: Path | None = None) -> None:
    """Run the MCP stdio server until stdin is closed.

    Each line from stdin is expected to be a complete JSON-RPC message.
    Each response is written as a single JSON line to stdout.
    """
    if root is not None:
        import os
        os.chdir(root)

    # Signal readiness on stderr so callers can detect the server is running
    sys.stderr.write(
        f"agentmd MCP server v{__version__} — listening on stdio\n"
    )
    sys.stderr.flush()

    for raw_line in sys.stdin:
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            msg = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            response = _error(None, -32700, f"Parse error: {exc}")
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()
            continue

        try:
            response = _dispatch(msg)
        except Exception as exc:
            response = _error(
                msg.get("id"),
                -32603,
                f"Internal error: {exc}",
                traceback.format_exc(),
            )

        if response is not None:
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()
