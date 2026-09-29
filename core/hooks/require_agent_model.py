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
import sys

# forge-core.js's own agent() calls always carry one of these in tool_input.
# A call missing all of them is not a Workflow-runtime call and is subject to
# the general-purpose/model checks below.
FORGE_CORE_KEYS = ("label", "phase", "schema", "effort")

AGENT_MENU = (
    "Pass model and subagent_type. Choices: scout (opus; reading and judgment), "
    "worker (opus; mechanical edits and tests), locator (haiku; where-is lookups), "
    "shipper (sonnet; commit, push, PR), browser (sonnet; browser QA)."
)


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

    model_value = tool_input.get("model")
    if not model_value:
        print(f"Blocked by require_agent_model hook: Agent call has no model. {AGENT_MENU}", file=sys.stderr)
        return 2

    subagent_type = tool_input.get("subagent_type")
    if subagent_type in ("general-purpose", "claude", None, ""):
        print(
            "Blocked by require_agent_model hook: general-purpose agents run outside forge-core "
            f"are not allowed. {AGENT_MENU}",
            file=sys.stderr,
        )
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
