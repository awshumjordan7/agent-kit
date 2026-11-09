#!/usr/bin/env python3
"""PreToolUse guard: every hand-written Agent tool call must name a custom agent
type, and that agent's file must set a model unless the call passes one.

Why: an Agent call with no model and no agent file model silently inherits the
session model. Each agent's model and effort live in its frontmatter
(~/.claude/agents/*.md), so a call that names such an agent needs no `model`;
`model` on the call is an override. forge-core.js's own agent() calls always
carry `label`/`phase`/`schema`/`effort` in `tool_input` and are not checked.
general-purpose/claude calls outside forge-core are blocked. The block message
lists the agent files.

Fail-open by design: any unexpected input or parse error exits 0 (allow). This is a routing nudge, not a security
boundary.

Exit codes: 2 = block (stderr is shown to Claude), 0 = allow.
"""

import json
import sys
from pathlib import Path

# forge-core.js's own agent() calls always carry one of these in tool_input.
# A call missing all of them is not a Workflow-runtime call and is subject to
# the agent-type and model checks below.
FORGE_CORE_KEYS = ("label", "phase", "schema", "effort")

MENU_LEAD = "Pass subagent_type; the agent file supplies the model and effort, so pass model only to override it."
STATIC_AGENT_MENU = (
    f"{MENU_LEAD} Choices: scout (opus; reading and judgment), "
    "worker (opus; mechanical edits and tests), locator (haiku; where-is lookups), "
    "shipper (opus; commit, push, PR), browser (opus; browser QA)."
)


def _frontmatter(text: str) -> dict[str, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    fields: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        key, sep, value = line.partition(":")
        if sep and not line.startswith((" ", "\t")):
            fields[key.strip()] = value.strip().strip("\"'")
    return fields


def agent_files() -> dict[str, dict[str, str]]:
    agents: dict[str, dict[str, str]] = {}
    try:
        for path in (Path.home() / ".claude" / "agents").glob("*.md"):
            fields = _frontmatter(path.read_text(encoding="utf-8"))
            agents[fields.get("name") or path.stem] = fields
    except (OSError, UnicodeError, RuntimeError):
        return {}
    return agents


def agent_menu(agents: dict[str, dict[str, str]]) -> str:
    if not agents:
        return STATIC_AGENT_MENU
    entries = [
        f"{name} ({fields.get('model') or 'inherit'}, {fields.get('effort') or 'session effort'})"
        for name, fields in sorted(agents.items())
    ]
    return f"{MENU_LEAD} Choices: {', '.join(entries)}."


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError, UnicodeError):
        return 0

    if not isinstance(payload, dict):
        return 0

    if payload.get("tool_name") != "Agent":
        return 0

    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return 0

    if tool_input.get("subagent_type") == "fork":
        return 0

    if any(key in tool_input for key in FORGE_CORE_KEYS):
        return 0

    agents = agent_files()
    subagent_type = tool_input.get("subagent_type")
    if subagent_type in ("general-purpose", "claude", None, ""):
        print(
            "Blocked by require_agent_model hook: general-purpose agents run outside forge-core "
            f"are not allowed. {agent_menu(agents)}",
            file=sys.stderr,
        )
        return 2
    if not isinstance(subagent_type, str):
        return 0

    if tool_input.get("model") or agents.get(subagent_type, {}).get("model"):
        return 0

    print(
        f"Blocked by require_agent_model hook: agent type {subagent_type} has no agent file "
        f"that sets a model, and the call passes none. {agent_menu(agents)}",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
