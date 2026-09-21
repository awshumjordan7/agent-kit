#!/usr/bin/env python3
"""PreToolUse guard: every Agent tool call must carry an explicit model, and
hand-written general-purpose/claude sub-agent calls are not allowed.

Why: forge-core.js sets `model` from its role profile on every agent() call it
makes, and those calls always carry `label`/`phase`/`schema`/`effort` in
`tool_input`. A call missing all of those is a hand-written Agent invocation
outside forge-core, which is exactly the case that has drifted from "every
sub-agent gets an explicit model" (see CLAUDE.md's Model Routing table) in the
past -- an omitted `model` silently inherits the session model instead of the
role-appropriate one.

Fail-open by design, same contract as block_secret_reads.py: any unexpected
input or parse error exits 0 (allow). This is a routing nudge, not a security
boundary.

Exit codes: 2 = block (stderr is shown to Claude), 0 = allow.
"""

import json
import re
import sys

# forge-core.js's own agent() calls always carry one of these in tool_input.
# A call missing all of them is not a Workflow-runtime call and is subject to
# the general-purpose/model checks below.
FORGE_CORE_KEYS = ("label", "phase", "schema", "effort")

# Heuristic order matters: first match wins.
HEURISTICS = (
    (
        re.compile(r"\bcommit\b|\bpush\b|open a pr\b|pull request", re.IGNORECASE),
        "shipper",
        "sonnet",
    ),
    (re.compile(r"where is|find |locate|grep|call sites", re.IGNORECASE), "locator", "haiku"),
    (
        re.compile(
            r"\brun |\btest\b|\bedit\b|\bapply\b|\bmove\b|\brename\b|\bformat\b|\brender\b|\binstall\b",
            re.IGNORECASE,
        ),
        "worker",
        "sonnet",
    ),
)
DEFAULT_AGENT = ("scout", "sonnet")


def pick_agent(description: str, prompt: str) -> tuple[str, str]:
    text = f"{description}\n{prompt}".lower()
    for pattern, agent, model in HEURISTICS:
        if pattern.search(text):
            return agent, model
    return DEFAULT_AGENT


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError, UnicodeError):
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

    description = tool_input.get("description") or ""
    prompt = tool_input.get("prompt") or ""
    if not isinstance(description, str):
        description = ""
    if not isinstance(prompt, str):
        prompt = ""
    agent, model = pick_agent(description, prompt)

    model_value = tool_input.get("model")
    if not model_value:
        print(
            "Blocked by require_agent_model hook: Agent call has no model. "
            f"Every sub-agent gets an explicit model; use {agent} ({model}) and "
            "pass model explicitly.",
            file=sys.stderr,
        )
        return 2

    subagent_type = tool_input.get("subagent_type")
    if subagent_type in ("general-purpose", "claude", None, ""):
        print(
            "Blocked by require_agent_model hook: general-purpose agents run "
            f"outside forge-core are not allowed; use {agent} ({model}) instead.",
            file=sys.stderr,
        )
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
