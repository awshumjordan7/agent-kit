from __future__ import annotations

import json
import re
from pathlib import Path

from aisetup.layers import resolve_layers
from aisetup.manifest import McpServer
from aisetup.mcp import McpPlan, _scope, plans_for_layers, register_servers
from aisetup.profile import load_profile

DEFAULT_HOME = Path("~/.claude").expanduser()

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
    print(f"URL: {server.get('url', '')}")
    print("Environment:")
    for key, value in server.get("env", {}).items():
        print(f"  {key}={value}")
    raise SystemExit(0)
if args[:2] == ["mcp", "remove"]:
    state.pop(name, None)
    state_path.write_text(json.dumps(state))
    raise SystemExit(0)
if args[:2] == ["mcp", "add"]:
    transport = args[args.index("--transport") + 1]
    scope = args[args.index("--scope") + 1]
    env = {}
    for index, value in enumerate(args):
        if value == "--env":
            key, env_value = args[index + 1].split("=", 1)
            env[key] = env_value
    if transport == "stdio":
        separator = args.index("--")
        name = args[separator - 1]
        server = {
            "transport": transport,
            "scope": scope,
            "command": args[separator + 1],
            "args": args[separator + 2:],
            "env": env,
        }
    else:
        name = args[-2]
        server = {
            "transport": transport,
            "scope": scope,
            "url": args[-1],
            "env": env,
        }
    if name in state:
        print("already exists", file=sys.stderr)
        raise SystemExit(1)
    state[name] = server
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

    assert register_servers((_plan("tool"),), home=DEFAULT_HOME) == ("skip demo",)
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

    assert register_servers((_plan("new"),), home=DEFAULT_HOME) == ("add demo",)
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

    assert register_servers((_plan("tool", env={"API_KEY": "new"}),), home=DEFAULT_HOME) == (
        "add demo",
    )
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

    assert register_servers((_plan("tool", scope="project"),), home=DEFAULT_HOME) == ("add demo",)
    assert "mcp remove demo --scope user" in log.read_text(encoding="utf-8")


def test_real_cli_capture_parses_like_the_fake():
    capture = (Path(__file__).parent / "fixtures/captures/claude-mcp-get-user.txt").read_text(
        encoding="utf-8"
    )
    assert _scope(capture) == "user"
    labels = set(re.findall(r"^\s+([A-Za-z ]+):", capture, re.MULTILINE))
    fake_labels = set(re.findall(r'print\(f?"([A-Za-z ]+):', FAKE_CLAUDE))
    assert labels <= fake_labels | {"Status"}


def test_overlay_servers_follow_module_servers(repo_root, monkeypatch):
    monkeypatch.chdir(repo_root)
    profile = load_profile(repo_root / "tests/fixtures/profiles/overlay-example.json")

    plans = plans_for_layers(resolve_layers(profile), profile)
    names = [plan.server.name for plan in plans]

    assert names[-1] == "example-http"
    assert "context7" in names[:-1]
    assert plans[-1].server.url == "https://example.invalid/mcp?api_key=fixture-token"


def test_fake_cli_records_stdio_and_overlay_http_adds(repo_root, fake_cli, tmp_path, monkeypatch):
    monkeypatch.chdir(repo_root)
    overlay = tmp_path / "overlay"
    overlay.mkdir()
    (overlay / "overlay.toml").write_text(
        'name = "demo"\ndescription = "Demo"\n'
        '[[mcp]]\nname = "overlay-stdio"\ntransport = "stdio"\nscope = "user"\n'
        'command = "tool"\nargs = ["serve"]\n'
        '[[mcp]]\nname = "overlay-http"\ntransport = "http"\nscope = "user"\n'
        'url = "https://example.invalid/mcp"\n',
        encoding="utf-8",
    )
    profile = load_profile(repo_root / "tests/fixtures/profiles/public-default.json")
    profile["layers"]["overlay"] = {"path": str(overlay)}
    state = tmp_path / "state.json"
    log = tmp_path / "log.txt"
    monkeypatch.setenv("FAKE_MCP_STATE", str(state))
    monkeypatch.setenv("FAKE_MCP_LOG", str(log))
    fake_cli("claude", FAKE_CLAUDE)

    register_servers(plans_for_layers(resolve_layers(profile), profile), home=DEFAULT_HOME)

    lines = log.read_text(encoding="utf-8").splitlines()
    assert any("--transport stdio overlay-stdio -- tool serve" in line for line in lines)
    assert any(
        "--transport http overlay-http https://example.invalid/mcp" in line for line in lines
    )


def test_overlay_secret_question_renders_in_args_and_is_redacted(repo_root, tmp_path, monkeypatch):
    monkeypatch.chdir(repo_root)
    overlay = tmp_path / "overlay"
    overlay.mkdir()
    (overlay / "overlay.toml").write_text(
        'name = "demo"\ndescription = "Demo"\n'
        '[[questions]]\nid = "token"\nprompt = "Token"\ntype = "string"\n'
        'default = ""\nsecret = true\n'
        '[[mcp]]\nname = "overlay-stdio"\ntransport = "stdio"\nscope = "user"\n'
        'command = "tool"\nargs = ["serve", "{{answers.overlay.token}}"]\n',
        encoding="utf-8",
    )
    profile = load_profile(repo_root / "tests/fixtures/profiles/public-default.json")
    profile["layers"]["overlay"] = {"path": str(overlay)}
    profile["answers"]["overlay.token"] = "secret-value"

    plan = next(
        plan
        for plan in plans_for_layers(resolve_layers(profile), profile)
        if plan.server.name == "overlay-stdio"
    )
    dry_run = register_servers((plan,), home=DEFAULT_HOME, dry_run=True)[0]

    assert plan.server.args == ("serve", "secret-value")
    assert "<redacted>" in dry_run
    assert "secret-value" not in dry_run


def test_nondefault_home_skips_all_claude_calls(fake_cli, tmp_path, monkeypatch, capsys):
    state = tmp_path / "state.json"
    log = tmp_path / "log.txt"
    monkeypatch.setenv("FAKE_MCP_STATE", str(state))
    monkeypatch.setenv("FAKE_MCP_LOG", str(log))
    fake_cli("claude", FAKE_CLAUDE)

    commands = register_servers((_plan("tool"),), home=tmp_path / "custom-home")

    assert commands == ("claude mcp add --scope user --transport stdio demo -- tool serve",)
    assert not log.exists()
    assert capsys.readouterr().out == (
        "mcp: skipped 1 server(s) because --home is not the default (demo)\n"
    )


def test_nondefault_home_marks_dry_run_commands_as_skipped(tmp_path, capsys):
    commands = register_servers((_plan("tool"),), home=tmp_path / "custom-home", dry_run=True)

    assert commands == (
        "claude mcp add --scope user --transport stdio demo -- tool serve [skipped: --home]",
    )
    assert capsys.readouterr().out == (
        "mcp: skipped 1 server(s) because --home is not the default (demo)\n"
    )
