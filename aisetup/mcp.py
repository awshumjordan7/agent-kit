from __future__ import annotations

import re
import shlex
import subprocess
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from aisetup.layers import ResolvedLayers
from aisetup.manifest import McpServer
from aisetup.paths import is_default_claude_home
from aisetup.render import RenderError, render_text


class McpError(RuntimeError):
    pass


@dataclass(frozen=True)
class McpPlan:
    server: McpServer
    env: dict[str, str]
    display_server: McpServer | None = None


def _answer_context(
    layers: ResolvedLayers, profile: dict[str, Any], *, redact: bool = False
) -> dict[str, Any]:
    answers: dict[str, dict[str, Any]] = {}
    question_sets = list(layers.module_manifests.items())
    for name, manifest in layers.module_manifests.items():
        answers[name] = {question.id: question.default for question in manifest.questions}
    for layer in layers.layers:
        if layer.overlay is not None:
            question_sets.append(("overlay", layer.overlay))
            answers["overlay"] = {
                question.id: question.default for question in layer.overlay.questions
            }
    for key, value in profile.get("answers", {}).items():
        module, _, question = key.partition(".")
        answers.setdefault(module, {})[question] = value
    if redact:
        for name, manifest in question_sets:
            for question in manifest.questions:
                if question.secret and answers.get(name, {}).get(question.id):
                    answers[name][question.id] = "<redacted>"
    return {"answers": answers}


def _render_server(server: McpServer, context: dict[str, Any]) -> McpServer:
    source = f"mcp:{server.name}"

    def render(value: str | None) -> str | None:
        return render_text(value, context, source=source) if value is not None else None

    env = {key: render_text(value, context, source=source) for key, value in server.env.items()}
    headers = {
        key: render_text(value, context, source=source) for key, value in server.headers.items()
    }
    return replace(
        server,
        command=render(server.command),
        args=tuple(render_text(value, context, source=source) for value in server.args),
        env={key: value for key, value in env.items() if value},
        headers={key: value for key, value in headers.items() if value},
        url=render(server.url),
    )


def plans_for_layers(layers: ResolvedLayers, profile: dict[str, Any]) -> tuple[McpPlan, ...]:
    context = _answer_context(layers, profile)
    display_context = _answer_context(layers, profile, redact=True)
    plans: list[McpPlan] = []
    for layer in layers.layers:
        manifest = layer.module or layer.overlay
        if manifest is None:
            continue
        for server in manifest.mcp:
            try:
                rendered = _render_server(server, context)
                display = _render_server(server, display_context)
            except RenderError as error:
                raise McpError(str(error)) from error
            plans.append(McpPlan(rendered, rendered.env, display))
    return tuple(plans)


def registration_for_layers(
    layers: ResolvedLayers, profile: dict[str, Any]
) -> tuple[tuple[McpPlan, ...], tuple[str, ...]]:
    plans = plans_for_layers(layers, profile)
    planned = {plan.server.name for plan in plans}
    declared = {
        server.name for manifest in layers.module_manifests.values() for server in manifest.mcp
    }
    for layer in layers.layers:
        if layer.overlay is not None:
            declared.update(server.name for server in layer.overlay.mcp)
    return plans, tuple(sorted(declared - planned))


def add_command(plan: McpPlan, *, redact: bool = False) -> list[str]:
    server = plan.display_server if redact and plan.display_server is not None else plan.server
    env = server.env if redact and plan.display_server is not None else plan.env
    command = ["claude", "mcp", "add", "--scope", server.scope, "--transport", server.transport]
    for key, value in sorted(env.items()):
        command.extend(["--env", f"{key}={'<redacted>' if redact else value}"])
    for key, value in sorted(server.headers.items()):
        command.extend(["--header", f"{key}: {value}"])
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
    headers = _headers(output)
    if headers is not None and headers != server.headers:
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


def _headers(output: str) -> dict[str, str] | None:
    headers: dict[str, str] = {}
    reading_headers = False
    for line in output.splitlines():
        if re.match(r"^\s*Headers:\s*$", line):
            reading_headers = True
            continue
        if not reading_headers:
            continue
        match = re.match(r"^\s+([^:]+):\s*(.*)$", line)
        if not match:
            if line.strip():
                break
            continue
        headers[match.group(1)] = match.group(2)
    return headers if reading_headers else None


def _scope(output: str) -> str | None:
    match = re.search(r"^\s*Scope:\s*(.+?)\s*$", output, re.MULTILINE)
    return _normalize_scope(match.group(1)) if match else None


def _run(
    command: list[str], *, display_command: str | None = None
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        command_text = display_command or shlex.join(command)
        raise McpError(f"MCP command failed: {command_text}: {type(error).__name__}") from None


def register_servers(
    plans: tuple[McpPlan, ...], *, home: Path, dry_run: bool = False, retire: tuple[str, ...] = ()
) -> tuple[str, ...]:
    commands = tuple(shlex.join(add_command(plan, redact=True)) for plan in plans)
    if not is_default_claude_home(home):
        names = ", ".join(plan.server.name for plan in plans)
        sys.stdout.write(
            f"mcp: skipped {len(plans)} server(s) because --home is not the default ({names})\n"
        )
        if dry_run:
            return tuple(f"{command} [skipped: --home]" for command in commands)
        return commands

    actions: list[str] = []
    for name in retire:
        if dry_run:
            actions.append(f"mcp: would remove {name} (module off)")
            continue
        current = _run(["claude", "mcp", "get", name])
        if current.returncode != 0:
            continue
        current_scope = _scope(current.stdout) or "user"
        removed = _run(["claude", "mcp", "remove", name, "--scope", current_scope])
        if removed.returncode != 0:
            raise McpError(removed.stderr.strip() or f"could not remove MCP server {name}")
        actions.append(f"remove {name}")
    for plan, command in zip(plans, commands, strict=True):
        server = plan.server
        if dry_run:
            actions.append(command)
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
        added = _run(add_command(plan), display_command=command)
        if added.returncode != 0:
            raise McpError(added.stderr.strip() or f"could not add MCP server {server.name}")
        actions.append(f"add {server.name}")
    return tuple(actions)
