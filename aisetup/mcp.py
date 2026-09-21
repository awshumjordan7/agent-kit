from __future__ import annotations

import re
import shlex
import subprocess
from dataclasses import dataclass
from typing import Any

from aisetup.layers import ResolvedLayers
from aisetup.manifest import McpServer
from aisetup.render import RenderError, render_text


class McpError(RuntimeError):
    pass


@dataclass(frozen=True)
class McpPlan:
    server: McpServer
    env: dict[str, str]


def _answer_context(layers: ResolvedLayers, profile: dict[str, Any]) -> dict[str, Any]:
    answers: dict[str, dict[str, Any]] = {}
    for name, manifest in layers.module_manifests.items():
        answers[name] = {question.id: question.default for question in manifest.questions}
    for key, value in profile.get("answers", {}).items():
        module, _, question = key.partition(".")
        answers.setdefault(module, {})[question] = value
    return {"answers": answers}


def plans_for_layers(layers: ResolvedLayers, profile: dict[str, Any]) -> tuple[McpPlan, ...]:
    context = _answer_context(layers, profile)
    plans: list[McpPlan] = []
    for layer in layers.layers:
        if layer.module is None:
            continue
        for server in layer.module.mcp:
            try:
                env = {
                    key: render_text(value, context, source=f"mcp:{server.name}")
                    for key, value in server.env.items()
                }
                env = {key: value for key, value in env.items() if value}
            except RenderError as error:
                raise McpError(str(error)) from error
            plans.append(McpPlan(server, env))
    return tuple(plans)


def add_command(plan: McpPlan, *, redact: bool = False) -> list[str]:
    server = plan.server
    command = ["claude", "mcp", "add", "--scope", server.scope, "--transport", server.transport]
    for key, value in sorted(plan.env.items()):
        command.extend(["--env", f"{key}={'<redacted>' if redact else value}"])
    command.append(server.name)
    if server.transport == "http":
        if not server.url:
            raise McpError(f"MCP server {server.name} has no URL")
        command.append(server.url)
    else:
        if not server.command:
            raise McpError(f"MCP server {server.name} has no command")
        command.extend(["--", server.command, *server.args])
    return command


def _matches(plan: McpPlan, output: str) -> bool:
    server = plan.server
    type_match = re.search(r"^\s*Type:\s*(\S+)\s*$", output, re.MULTILINE)
    scope_match = re.search(r"^\s*Scope:\s*(.+?)\s*$", output, re.MULTILINE)
    if not type_match or type_match.group(1) != server.transport:
        return False
    if not scope_match or _normalize_scope(scope_match.group(1)) != server.scope:
        return False
    if _environment(output) != plan.env:
        return False
    if server.transport == "http":
        url_match = re.search(r"^\s*URL:\s*(.+?)\s*$", output, re.MULTILINE)
        return bool(url_match and url_match.group(1) == server.url)
    command_match = re.search(r"^\s*Command:\s*(.+?)\s*$", output, re.MULTILINE)
    args_match = re.search(r"^\s*Args:\s*(.*?)\s*$", output, re.MULTILINE)
    actual_args = tuple(shlex.split(args_match.group(1))) if args_match else ()
    return bool(
        command_match and command_match.group(1) == server.command and actual_args == server.args
    )


def _normalize_scope(scope: str) -> str:
    words = scope.strip().split()
    return words[0].lower() if words else ""


def _environment(output: str) -> dict[str, str]:
    environment: dict[str, str] = {}
    reading_environment = False
    for line in output.splitlines():
        if re.match(r"^\s*Environment:\s*$", line):
            reading_environment = True
            continue
        if not reading_environment:
            continue
        match = re.match(r"^\s+([^=\s]+)=(.*)$", line)
        if not match:
            if line.strip():
                break
            continue
        environment[match.group(1)] = match.group(2)
    return environment


def _scope(output: str) -> str | None:
    match = re.search(r"^\s*Scope:\s*(.+?)\s*$", output, re.MULTILINE)
    return _normalize_scope(match.group(1)) if match else None


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise McpError(f"MCP command failed: {shlex.join(command)}: {error}") from error


def register_servers(plans: tuple[McpPlan, ...], *, dry_run: bool = False) -> tuple[str, ...]:
    actions: list[str] = []
    for plan in plans:
        server = plan.server
        if dry_run:
            action = shlex.join(add_command(plan, redact=True))
            actions.append(action)
            continue
        current = _run(["claude", "mcp", "get", server.name])
        if current.returncode == 0 and _matches(plan, current.stdout):
            actions.append(f"skip {server.name}")
            continue
        if current.returncode == 0:
            current_scope = _scope(current.stdout) or server.scope
            removed = _run(["claude", "mcp", "remove", server.name, "--scope", current_scope])
            if removed.returncode != 0:
                raise McpError(
                    removed.stderr.strip() or f"could not remove MCP server {server.name}"
                )
        added = _run(add_command(plan))
        if added.returncode != 0:
            raise McpError(added.stderr.strip() or f"could not add MCP server {server.name}")
        actions.append(f"add {server.name}")
    return tuple(actions)
