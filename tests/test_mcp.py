from __future__ import annotations

import json

from aisetup.manifest import McpServer
from aisetup.mcp import McpPlan, register_servers

FAKE_CLAUDE = r"""
import json
import os
import sys
from pathlib import Path

state_path = Path(os.environ["FAKE_MCP_STATE"])
log_path = Path(os.environ["FAKE_MCP_LOG"])
state = json.loads(state_path.read_text()) if state_path.exists() else {}
args = sys.argv[1:]
name = args[2]
with log_path.open("a") as log:
    log.write(" ".join(args) + "\n")
if args[:2] == ["mcp", "get"]:
    server = state.get(name)
    if not server:
        raise SystemExit(1)
    print(f"Type: {server['transport']}")
    print(f"Scope: {server.get('scope', 'user').capitalize()} config (available in all your projects)")
    print(f"Command: {server.get('command', '')}")
    print(f"Args: {' '.join(server.get('args', []))}")
    print("Environment:")
    for key, value in server.get("env", {}).items():
        print(f"  {key}={value}")
    raise SystemExit(0)
if args[:2] == ["mcp", "remove"]:
    state.pop(name, None)
    state_path.write_text(json.dumps(state))
    raise SystemExit(0)
if args[:2] == ["mcp", "add"]:
    name_index = args.index("--") - 1
    name = args[name_index]
    if name in state:
        print("already exists", file=sys.stderr)
        raise SystemExit(1)
    state[name] = {"transport": "stdio", "command": args[name_index + 2], "args": args[name_index + 3:]}
    state_path.write_text(json.dumps(state))
    raise SystemExit(0)
raise SystemExit(2)
"""


def _plan(command: str, *, scope: str = "user", env: dict[str, str] | None = None) -> McpPlan:
    return McpPlan(McpServer("demo", "stdio", scope, command, ("serve",)), env or {})


def test_identical_server_is_skipped(fake_cli, tmp_path, monkeypatch):
    state = tmp_path / "state.json"
    log = tmp_path / "log.txt"
    state.write_text(
        json.dumps({"demo": {"transport": "stdio", "command": "tool", "args": ["serve"]}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("FAKE_MCP_STATE", str(state))
    monkeypatch.setenv("FAKE_MCP_LOG", str(log))
    fake_cli("claude", FAKE_CLAUDE)

    assert register_servers((_plan("tool"),)) == ("skip demo",)
    assert "mcp add" not in log.read_text(encoding="utf-8")


def test_changed_server_is_removed_then_added_once(fake_cli, tmp_path, monkeypatch):
    state = tmp_path / "state.json"
    log = tmp_path / "log.txt"
    state.write_text(
        json.dumps({"demo": {"transport": "stdio", "command": "old", "args": ["serve"]}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("FAKE_MCP_STATE", str(state))
    monkeypatch.setenv("FAKE_MCP_LOG", str(log))
    fake_cli("claude", FAKE_CLAUDE)

    assert register_servers((_plan("new"),)) == ("add demo",)
    lines = log.read_text(encoding="utf-8").splitlines()
    assert sum(line.startswith("mcp add") for line in lines) == 1
    assert any(line.startswith("mcp remove") for line in lines)


def test_changed_environment_is_removed_then_added(fake_cli, tmp_path, monkeypatch):
    state = tmp_path / "state.json"
    log = tmp_path / "log.txt"
    state.write_text(
        json.dumps(
            {
                "demo": {
                    "transport": "stdio",
                    "scope": "user",
                    "command": "tool",
                    "args": ["serve"],
                    "env": {"API_KEY": "old"},
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("FAKE_MCP_STATE", str(state))
    monkeypatch.setenv("FAKE_MCP_LOG", str(log))
    fake_cli("claude", FAKE_CLAUDE)

    assert register_servers((_plan("tool", env={"API_KEY": "new"}),)) == ("add demo",)
    assert "mcp remove demo --scope user" in log.read_text(encoding="utf-8")


def test_changed_scope_is_removed_from_old_scope(fake_cli, tmp_path, monkeypatch):
    state = tmp_path / "state.json"
    log = tmp_path / "log.txt"
    state.write_text(
        json.dumps(
            {
                "demo": {
                    "transport": "stdio",
                    "scope": "user",
                    "command": "tool",
                    "args": ["serve"],
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("FAKE_MCP_STATE", str(state))
    monkeypatch.setenv("FAKE_MCP_LOG", str(log))
    fake_cli("claude", FAKE_CLAUDE)

    assert register_servers((_plan("tool", scope="project"),)) == ("add demo",)
    assert "mcp remove demo --scope user" in log.read_text(encoding="utf-8")
