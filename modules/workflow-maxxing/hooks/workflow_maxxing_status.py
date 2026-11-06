#!/usr/bin/env python3
"""Claude Code hook: forward the hook event to the workflow-maxxing app socket.

Does nothing outside the app (any WORKFLOW_MAXXING_* variable missing).
Prints nothing and always exits 0, so a missing or hung app never blocks Claude Code.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import time

DEADLINE_SECONDS = 0.5


def _text(payload: dict, key: str) -> str | None:
    value = payload.get(key)
    return value if isinstance(value, str) else None


def _remaining(deadline: float) -> float:
    left = deadline - time.monotonic()
    if left <= 0:
        raise TimeoutError("workflow-maxxing socket deadline passed")
    return left


def _send(path: str, line: bytes, deadline: float) -> None:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(_remaining(deadline))
        client.connect(path)
        client.settimeout(_remaining(deadline))
        client.sendall(line)
        reply = b""
        while b"\n" not in reply:
            client.settimeout(_remaining(deadline))
            chunk = client.recv(4096)
            if not chunk:
                break
            reply += chunk


def main() -> int:
    socket_path = os.environ.get("WORKFLOW_MAXXING_SOCKET")
    pty = os.environ.get("WORKFLOW_MAXXING_PTY")
    token = os.environ.get("WORKFLOW_MAXXING_TOKEN")
    if not socket_path or not pty or not token:
        return 0
    try:
        payload = json.load(sys.stdin)
        deadline = time.monotonic() + DEADLINE_SECONDS
        if not isinstance(payload, dict):
            return 0
        event = _text(payload, "hook_event_name")
        session_id = _text(payload, "session_id")
        if not event or not session_id:
            return 0
        request = {
            "v": 1,
            "type": "hook",
            "pty": pty,
            "token": token,
            "event": event,
            "sessionId": session_id,
            "tool": _text(payload, "tool_name"),
            "notificationType": _text(payload, "notification_type"),
            "message": _text(payload, "message"),
            "source": _text(payload, "source") or _text(payload, "reason"),
        }
        _send(socket_path, (json.dumps(request) + "\n").encode(), deadline)
    except (OSError, ValueError):
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
