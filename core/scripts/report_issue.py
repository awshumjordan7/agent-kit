from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

CATEGORIES = {"bug", "inconvenience", "redundancy", "cost", "flag", "suggestion"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="report_issue.py")
    parser.add_argument("--session")
    parser.add_argument("command")
    parser.add_argument("values", nargs="*")
    args = parser.parse_args(argv)
    feedback_dir = Path(os.environ.get("FEEDBACK_DIR", "~/.claude/feedback")).expanduser()
    feedback_dir.mkdir(parents=True, exist_ok=True)
    inbox = feedback_dir / "inbox.jsonl"

    if args.command in CATEGORIES and 1 <= len(args.values) <= 2:
        entry = {
            "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
            "session": args.session or os.environ.get("CLAUDE_SESSION_NAME", "unknown"),
            "cwd": str(Path.cwd()),
            "category": args.command,
            "text": args.values[0],
            "evidence": args.values[1] if len(args.values) == 2 else None,
            "read": False,
        }
        with inbox.open("a", encoding="utf-8") as file:
            file.write(json.dumps(entry) + "\n")
        return 0
    parser.print_usage(sys.stderr)
    return 64


if __name__ == "__main__":
    raise SystemExit(main())
