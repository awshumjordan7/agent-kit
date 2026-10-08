#!/usr/bin/env python3
"""Stop hook: append the user's new messages to the run dir's user-log.md.

Does nothing outside a run dir (no STATE.md named in the resume prompt or in the cwd).
Always exits 0; a failure prints one warning line.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# The installer copies hooks/ and scripts/ side by side, as they sit in the repo.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from run_dir import resolve_run_dir
from user_log import sync


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0
    if not isinstance(payload, dict) or payload.get("agent_id"):
        return 0
    transcript_path = payload.get("transcript_path")
    if not isinstance(transcript_path, str) or not Path(transcript_path).is_file():
        return 0
    session_id = payload.get("session_id")
    cwd = payload.get("cwd")
    run_dir = resolve_run_dir(cwd if isinstance(cwd, str) else None, transcript_path)
    if run_dir is None:
        return 0
    sync(Path(transcript_path), run_dir, session_id if isinstance(session_id, str) else None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
