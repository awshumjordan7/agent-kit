#!/usr/bin/env python3
"""UserPromptSubmit/PostToolUse/Stop hook: nag by context-size band, block once at 340k.

As a PreToolUse hook it guards only the claude-implementer sub-agent: one soft
block at 160k, then at 300k every tool call except progress-file edits and
StructuredOutput is blocked. Other sub-agents and the main session pass through.

Fail-open by design: exit 0 silently on any missing/unreadable transcript,
other subagent payload, or parse error, same contract as the other hooks here.
"""

import glob
import json
import os
import re
import sys

BAND_160K = 160_000
BAND_200K = 200_000
BAND_300K = 300_000
BAND_340K = 340_000
BANDS = (BAND_160K, BAND_200K, BAND_300K, BAND_340K)
RESET_BELOW = 120_000

STATE_DIR = os.environ.get("CONTEXT_GUARD_STATE_DIR") or os.path.expanduser(
    "~/.claude/hooks/state/context-guard"
)

REPORT_ISSUE_LINE = (
    "Before handing off, file any issues or suggestions with "
    "`python3 ~/.claude/scripts/report_issue.py` (skip if none)."
)

MESSAGES = {
    BAND_160K: (
        "Context guard: ~{n}k tokens. Plan the handoff now: take on no new large scope, "
        "keep STATE.md current."
    ),
    BAND_200K: (
        "Context guard: ~{n}k tokens. Finish the current step, then rewrite STATE.md from "
        "the template so the handoff is one command away."
    ),
    BAND_300K: (
        "Context guard: ~{n}k tokens. Start no new work. Let running agents and Codex "
        "sessions finish, rewrite STATE.md, then run "
        "`python3 ~/.claude/scripts/handoff.py <STATE.md> <new-session-name>` and message the "
        "successor. Exception: if this run is in its final stage (final review, QA, ship), "
        "finish it first, then hand off. " + REPORT_ISSUE_LINE
    ),
    BAND_340K: (
        "Context guard: ~{n}k tokens. Before ending this turn: wait for running agents, "
        "rewrite STATE.md, run handoff.py, message the successor, then end. Exception: a "
        "run in its final stage finishes first. " + REPORT_ISSUE_LINE
    ),
}


IMPLEMENTER_AGENT = "claude-implementer"
PROGRESS_MARKER = "/impl-progress-"
PROGRESS_TOOLS = ("Write", "Edit", "Read")
AGENT_ID_SHAPE = re.compile(r"^[\w-]+$")
IMPL_SOFT_MESSAGE = (
    "Context is at {n}k. If little work remains, retry this call and finish. "
    "Otherwise update your progress file and return status PARTIAL."
)
IMPL_HARD_MESSAGE = "Context limit reached. Update your progress file and return status PARTIAL now."


def find_last_assistant_usage(path, block_size=65536):
    """Read the file backward in chunks and return the last event with
    type == 'assistant' and a non-empty message.usage, without loading the
    whole file into memory.
    """
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        pos = f.tell()
        buffer = b""
        while pos > 0:
            read_size = min(block_size, pos)
            pos -= read_size
            f.seek(pos)
            chunk = f.read(read_size)
            buffer = chunk + buffer
            lines = buffer.split(b"\n")
            buffer = lines[0]
            for raw in reversed(lines[1:]):
                raw = raw.strip()
                if not raw:
                    continue
                ev = try_parse(raw)
                if ev is None:
                    continue
                if ev.get("type") == "assistant" and ev.get("message", {}).get("usage"):
                    return ev
        raw = buffer.strip()
        if raw:
            ev = try_parse(raw)
            if (
                ev is not None
                and ev.get("type") == "assistant"
                and ev.get("message", {}).get("usage")
            ):
                return ev
    return None


def try_parse(raw):
    try:
        return json.loads(raw)
    except (ValueError, OSError):
        return None


def measure_from_transcript(transcript_path):
    ev = find_last_assistant_usage(transcript_path)
    if ev is None:
        return None
    usage = ev.get("message", {}).get("usage", {})
    return (
        (usage.get("input_tokens", 0) or 0)
        + (usage.get("cache_creation_input_tokens", 0) or 0)
        + (usage.get("cache_read_input_tokens", 0) or 0)
    )


def load_state(state_path):
    try:
        with open(state_path) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError, ValueError):
        return {"band": 0, "blocked": False}
    return {"band": data.get("band", 0), "blocked": bool(data.get("blocked", False))}


def save_state(state_path, band, blocked):
    os.makedirs(os.path.dirname(state_path), exist_ok=True)
    tmp_path = state_path + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump({"band": band, "blocked": blocked}, f)
    os.replace(tmp_path, state_path)


def highest_crossed_band(measure):
    crossed = 0
    for band in BANDS:
        if measure >= band:
            crossed = band
    return crossed


def emit_hook_context(event_name, message):
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": event_name,
                    "additionalContext": message,
                }
            }
        )
    )


def emit_block(reason):
    print(json.dumps({"decision": "block", "reason": reason}))


def find_agent_transcript(transcript_path, session_id, agent_id):
    """Sub-agent transcripts live under <session dir>/subagents/, optionally
    nested under workflows/<runId>/."""
    name = f"agent-{agent_id}.jsonl"
    if os.path.basename(transcript_path) == name:
        return transcript_path
    root = os.path.join(os.path.dirname(transcript_path), session_id, "subagents")
    matches = glob.glob(os.path.join(glob.escape(root), "**", name), recursive=True)
    return matches[0] if matches else None


def progress_file_call(payload):
    tool_name = payload.get("tool_name")
    if tool_name == "StructuredOutput":
        return True
    if tool_name not in PROGRESS_TOOLS:
        return False
    tool_input = payload.get("tool_input")
    path = tool_input.get("file_path") if isinstance(tool_input, dict) else None
    return isinstance(path, str) and PROGRESS_MARKER in path


def deny_tool_call(message):
    print(f"Blocked by context_guard hook (claude-implementer context limit): {message}", file=sys.stderr)
    return 2


def implementer_pretool(payload):
    if payload.get("agent_type") != IMPLEMENTER_AGENT:
        return 0
    agent_id = payload.get("agent_id")
    session_id = payload.get("session_id")
    transcript_path = payload.get("transcript_path")
    if not all(isinstance(v, str) and v for v in (agent_id, session_id, transcript_path)):
        return 0
    if not AGENT_ID_SHAPE.match(agent_id):
        return 0
    agent_transcript = find_agent_transcript(transcript_path, session_id, agent_id)
    if not agent_transcript or not os.path.isfile(agent_transcript):
        return 0
    measure = measure_from_transcript(agent_transcript)
    if measure is None or measure < BAND_160K:
        return 0
    if measure >= BAND_300K:
        return 0 if progress_file_call(payload) else deny_tool_call(IMPL_HARD_MESSAGE)
    state_path = os.path.join(STATE_DIR, f"impl-{agent_id}.json")
    if load_state(state_path)["blocked"]:
        return 0
    # An unsaved warning would block every call, so a failed save allows this one.
    save_state(state_path, BAND_160K, True)
    return deny_tool_call(IMPL_SOFT_MESSAGE.format(n=measure // 1000))


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError, OSError):
        return 0
    if not isinstance(payload, dict):
        return 0

    if payload.get("hook_event_name") == "PreToolUse":
        if not payload.get("agent_id"):
            return 0
        try:
            return implementer_pretool(payload)
        except (ValueError, OSError):
            return 0

    if payload.get("agent_id"):
        return 0

    transcript_path = payload.get("transcript_path")
    if not transcript_path or not os.path.isfile(transcript_path):
        return 0

    session_id = payload.get("session_id")
    if not session_id:
        return 0

    event_name = payload.get("hook_event_name")

    try:
        measure = measure_from_transcript(transcript_path)
    except (ValueError, OSError):
        return 0
    if measure is None:
        return 0

    state_path = os.path.join(STATE_DIR, f"{session_id}.json")
    state = load_state(state_path)

    if measure < RESET_BELOW and (state["band"] or state["blocked"]):
        state = {"band": 0, "blocked": False}
        try:
            save_state(state_path, state["band"], state["blocked"])
        except OSError:
            return 0

    if event_name == "Stop":
        if measure >= BAND_340K and not payload.get("stop_hook_active") and not state["blocked"]:
            try:
                save_state(state_path, state["band"], True)
            except OSError:
                return 0
            emit_block(MESSAGES[BAND_340K].format(n=measure // 1000))
        return 0

    crossed = highest_crossed_band(measure)
    if crossed > BAND_300K:
        crossed = BAND_300K  # 340k is announced only via the Stop block
    if crossed > state["band"]:
        try:
            save_state(state_path, crossed, state["blocked"])
        except OSError:
            return 0
        emit_hook_context(event_name, MESSAGES[crossed].format(n=measure // 1000))

    return 0


if __name__ == "__main__":
    sys.exit(main())
