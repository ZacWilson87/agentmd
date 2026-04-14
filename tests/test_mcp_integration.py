"""Subprocess-level integration tests for the agentmd MCP server.

These tests start a real `agentmd mcp` process, send JSON-RPC 2.0 messages
over stdin, and verify the responses match the MCP protocol specification.

Each test is self-contained and uses tmp_path fixtures so the server operates
on a known, isolated directory.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

FLAT_FIXTURE = Path(__file__).parent / "fixtures" / "flat_repo"
OWN_ROOT = Path(__file__).parent.parent  # /home/user/agentmd


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def _mcp_session(root: Path, messages: list[dict]) -> tuple[list[dict], str]:
    """Start agentmd mcp, pipe messages, return (responses, stderr)."""
    proc = subprocess.Popen(
        ["agentmd", "mcp", "--root", str(root)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    payload = ("\n".join(json.dumps(m) for m in messages) + "\n").encode()
    stdout, stderr = proc.communicate(input=payload, timeout=15)
    responses = [
        json.loads(line)
        for line in stdout.decode().strip().splitlines()
        if line.strip()
    ]
    return responses, stderr.decode()


def _make_repo(tmp_path: Path) -> Path:
    """Create a minimal agentmd repo and return the root."""
    _write(tmp_path / "AGENTS.md", """\
---
agentmd: "1.0"
type: agents
name: "MCP Test Project"
scope: project
stack:
  - python
agent_instructions: "You are a test assistant."
skills:
  - skills/my-skill.skill.md
rules:
  - rules/no-raw-sql.rule.md
---
""")
    _write(tmp_path / "skills" / "my-skill.skill.md", """\
---
agentmd: "1.0"
type: skill
id: my-skill
version: "1.0"
description: "Test skill"
trigger: "when testing"
---

## Steps

1. Do the test.
""")
    _write(tmp_path / "rules" / "no-raw-sql.rule.md", """\
---
agentmd: "1.0"
type: rule
id: no-raw-sql
severity: error
description: "No raw SQL strings"
rationale: "Prevents injection"
applies_to:
  - "**/*.py"
---
""")
    _write(tmp_path / "src" / "main.py", "# main\n")
    return tmp_path


# ---------------------------------------------------------------------------
# TestMCPServerSubprocess
# ---------------------------------------------------------------------------

class TestMCPServerSubprocess:
    """End-to-end MCP server tests via subprocess stdin/stdout."""

    def test_stderr_has_readiness_message(self, tmp_path):
        root = _make_repo(tmp_path)
        _, stderr = _mcp_session(root, [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        ])
        assert "agentmd MCP server" in stderr
        assert "listening on stdio" in stderr

    def test_initialize_returns_server_info(self, tmp_path):
        root = _make_repo(tmp_path)
        responses, _ = _mcp_session(root, [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        ])
        assert len(responses) == 1
        result = responses[0]["result"]
        assert result["serverInfo"]["name"] == "agentmd"
        assert result["protocolVersion"] == "2024-11-05"
        assert "tools" in result["capabilities"]

    def test_notification_gets_no_response(self, tmp_path):
        """notifications/initialized has no 'id' — server must not respond."""
        root = _make_repo(tmp_path)
        responses, _ = _mcp_session(root, [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            # notification: no id field
            {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        ])
        # Only the initialize response — no response for the notification
        assert len(responses) == 1
        assert responses[0]["id"] == 1

    def test_tools_list_returns_all_six_tools(self, tmp_path):
        root = _make_repo(tmp_path)
        responses, _ = _mcp_session(root, [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        ])
        assert len(responses) == 2
        tool_names = {t["name"] for t in responses[1]["result"]["tools"]}
        expected = {
            "agentmd_resolve",
            "agentmd_list_skills",
            "agentmd_list_rules",
            "agentmd_validate",
            "agentmd_check",
            "agentmd_audit",
        }
        assert tool_names == expected

    def test_ping_returns_empty_result(self, tmp_path):
        root = _make_repo(tmp_path)
        responses, _ = _mcp_session(root, [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "ping", "params": {}},
        ])
        assert responses[1]["result"] == {}

    def test_malformed_json_returns_parse_error(self, tmp_path):
        """Server must respond with error code -32700 for invalid JSON."""
        root = _make_repo(tmp_path)
        proc = subprocess.Popen(
            ["agentmd", "mcp", "--root", str(root)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdout, _ = proc.communicate(input=b"not valid json\n", timeout=10)
        response = json.loads(stdout.decode().strip())
        assert "error" in response
        assert response["error"]["code"] == -32700

    def test_unknown_method_returns_method_not_found(self, tmp_path):
        root = _make_repo(tmp_path)
        responses, _ = _mcp_session(root, [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "nonexistent/method", "params": {}},
        ])
        assert "error" in responses[1]
        assert responses[1]["error"]["code"] == -32601

    # --- agentmd_resolve ---

    def test_agentmd_resolve_returns_export_schema(self, tmp_path):
        root = _make_repo(tmp_path)
        target = str(root / "src" / "main.py")
        responses, _ = _mcp_session(root, [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
             "params": {"name": "agentmd_resolve", "arguments": {"path": target}}},
        ])
        content_text = responses[1]["result"]["content"][0]["text"]
        data = json.loads(content_text)
        assert data["agents_file"]["name"] == "MCP Test Project"
        assert len(data["active_skills"]) == 1
        assert data["active_skills"][0]["id"] == "my-skill"
        assert data["active_skills"][0]["path"] is not None  # Bug 2 regression
        assert len(data["prompt_snippets"]) == 1
        assert "Trigger:" in data["prompt_snippets"][0]

    def test_agentmd_resolve_content_is_text_type(self, tmp_path):
        root = _make_repo(tmp_path)
        target = str(root / "src" / "main.py")
        responses, _ = _mcp_session(root, [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
             "params": {"name": "agentmd_resolve", "arguments": {"path": target}}},
        ])
        content = responses[1]["result"]["content"]
        assert content[0]["type"] == "text"

    # --- agentmd_list_skills ---

    def test_agentmd_list_skills_has_path_field(self, tmp_path):
        root = _make_repo(tmp_path)
        responses, _ = _mcp_session(root, [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
             "params": {"name": "agentmd_list_skills", "arguments": {}}},
        ])
        skills = json.loads(responses[1]["result"]["content"][0]["text"])
        assert len(skills) == 1
        assert skills[0]["id"] == "my-skill"
        assert "path" in skills[0]
        assert skills[0]["path"].endswith(".skill.md")

    # --- agentmd_list_rules ---

    def test_agentmd_list_rules_returns_rule_schema(self, tmp_path):
        root = _make_repo(tmp_path)
        responses, _ = _mcp_session(root, [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
             "params": {"name": "agentmd_list_rules", "arguments": {}}},
        ])
        rules = json.loads(responses[1]["result"]["content"][0]["text"])
        assert len(rules) == 1
        for key in ("id", "severity", "description", "applies_to", "exceptions", "path"):
            assert key in rules[0], f"Rule missing key: {key}"

    # --- agentmd_validate ---

    def test_agentmd_validate_returns_path_valid_error(self, tmp_path):
        root = _make_repo(tmp_path)
        responses, _ = _mcp_session(root, [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
             "params": {"name": "agentmd_validate", "arguments": {}}},
        ])
        results = json.loads(responses[1]["result"]["content"][0]["text"])
        assert len(results) >= 1
        for entry in results:
            assert "path" in entry
            assert "valid" in entry
            assert "error" in entry

    def test_agentmd_validate_clean_repo_all_valid(self, tmp_path):
        root = _make_repo(tmp_path)
        responses, _ = _mcp_session(root, [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
             "params": {"name": "agentmd_validate", "arguments": {}}},
        ])
        results = json.loads(responses[1]["result"]["content"][0]["text"])
        assert all(r["valid"] for r in results)

    # --- agentmd_check ---

    def test_agentmd_check_returns_violations_dict(self, tmp_path):
        root = _make_repo(tmp_path)
        target = str(root / "src" / "main.py")
        responses, _ = _mcp_session(root, [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
             "params": {"name": "agentmd_check", "arguments": {"path": target}}},
        ])
        result = json.loads(responses[1]["result"]["content"][0]["text"])
        assert "path" in result
        assert "violations" in result
        assert isinstance(result["violations"], dict)

    def test_agentmd_check_unknown_tool_error(self, tmp_path):
        root = _make_repo(tmp_path)
        responses, _ = _mcp_session(root, [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
             "params": {"name": "agentmd_nonexistent_tool", "arguments": {}}},
        ])
        assert "error" in responses[1]

    # --- agentmd_audit ---

    def test_agentmd_audit_has_passed_key(self, tmp_path):
        root = _make_repo(tmp_path)
        responses, _ = _mcp_session(root, [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
             "params": {"name": "agentmd_audit", "arguments": {}}},
        ])
        result = json.loads(responses[1]["result"]["content"][0]["text"])
        assert "passed" in result
        assert "summary" in result

    # --- full session test ---

    def test_full_mcp_session_all_tools(self, tmp_path):
        """Run all six tools in a single session — verifies no state leaks."""
        root = _make_repo(tmp_path)
        target = str(root / "src" / "main.py")
        responses, stderr = _mcp_session(root, [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
             "params": {"name": "agentmd_resolve", "arguments": {"path": target}}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
             "params": {"name": "agentmd_list_skills", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
             "params": {"name": "agentmd_list_rules", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 6, "method": "tools/call",
             "params": {"name": "agentmd_validate", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 7, "method": "tools/call",
             "params": {"name": "agentmd_check", "arguments": {"path": target}}},
            {"jsonrpc": "2.0", "id": 8, "method": "tools/call",
             "params": {"name": "agentmd_audit", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 9, "method": "ping", "params": {}},
        ])
        # notification has no response, so we expect 9 responses (ids 1-9)
        assert len(responses) == 9
        ids = [r["id"] for r in responses]
        assert ids == [1, 2, 3, 4, 5, 6, 7, 8, 9]
        # No errors
        for r in responses:
            assert "error" not in r, f"Unexpected error in response id={r['id']}: {r}"

    # --- own project as live fixture ---

    def test_own_project_mcp_resolve(self):
        """Smoke test: resolve context for the agentmd project's own cli.py."""
        target = str(OWN_ROOT / "agentmd" / "cli.py")
        responses, _ = _mcp_session(OWN_ROOT, [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
             "params": {"name": "agentmd_resolve", "arguments": {"path": target}}},
        ])
        data = json.loads(responses[1]["result"]["content"][0]["text"])
        assert data["agents_file"]["name"] == "agentmd"
        skill_ids = {s["id"] for s in data["active_skills"]}
        assert "add-cli-command" in skill_ids
        assert "add-file-type" in skill_ids
        # Bug 2 regression: path must be present
        for skill in data["active_skills"]:
            assert skill["path"] is not None

    def test_flat_fixture_mcp_resolve(self):
        """Smoke test: resolve using the checked-in flat_repo fixture."""
        target = str(FLAT_FIXTURE / "AGENTS.md")
        responses, _ = _mcp_session(FLAT_FIXTURE, [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
             "params": {"name": "agentmd_resolve", "arguments": {"path": target}}},
        ])
        data = json.loads(responses[1]["result"]["content"][0]["text"])
        assert data["agents_file"]["name"] == "Flat Repo Example"
        assert any(s["id"] == "scaffold-endpoint" for s in data["active_skills"])
