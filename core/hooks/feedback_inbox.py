#!/usr/bin/env python3
"""UserPromptSubmit hook: nudge the inbox owner about unread feedback entries.

Fail-open by design: any file or parse error exits 0 silently, same
contract as block_secret_reads.py, so a bug here never blocks a prompt.
"""

import json
import os
import sys

FEEDBACK_DIR = os.environ.get("FEEDBACK_DIR") or os.path.expanduser("~/.claude/feedback")
STATE_DIR = os.environ.get("FEEDBACK_STATE_DIR") or os.path.expanduser(
    "~/.claude/hooks/state/feedback-inbox"
)


def unread_count(inbox_path: str) -> int:
    with open(inbox_path) as f:
        lines = [line for line in f if line.strip()]
    count = 0
    for line in lines:
        entry = json.loads(line)
        if not entry.get("read"):
            count += 1
    return count


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError, OSError):
        return 0

    session_id = payload.get("session_id")
    if not session_id:
        return 0

    owner_path = os.path.join(FEEDBACK_DIR, "owner")
    try:
        with open(owner_path) as f:
            owner = f.read().strip()
    except OSError:
        return 0

    if owner != session_id:
        return 0

    inbox_path = os.path.join(FEEDBACK_DIR, "inbox.jsonl")
    try:
        count = unread_count(inbox_path)
    except (OSError, json.JSONDecodeError, ValueError):
        return 0

    state_path = os.path.join(STATE_DIR, session_id)
    last_count = None
    try:
        with open(state_path) as f:
            last_count = f.read().strip()
    except OSError:
        pass

    if count == 0:
        if last_count != "0":
            try:
                os.makedirs(STATE_DIR, exist_ok=True)
                with open(state_path, "w") as f:
                    f.write("0")
            except OSError:
                pass
        return 0

    if last_count == str(count):
        return 0

    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(state_path, "w") as f:
            f.write(str(count))
    except OSError:
        return 0

    message = (
        f"Feedback inbox: {count} unread. Run "
        "`python3 ~/.claude/scripts/report_issue.py list --unread` when convenient."
    )
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": message,
                }
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
