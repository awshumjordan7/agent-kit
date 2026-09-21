from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

CATEGORIES = {"bug", "inconvenience", "redundancy", "cost", "flag", "suggestion"}


def _entries(inbox: Path) -> list[dict[str, Any]]:
    if not inbox.is_file():
        return []
    return [json.loads(line) for line in inbox.read_text(encoding="utf-8").splitlines() if line]


def _write_entries(inbox: Path, entries: list[dict[str, Any]]) -> None:
    temporary = inbox.with_suffix(".tmp")
    temporary.write_text("".join(json.dumps(entry) + "\n" for entry in entries), encoding="utf-8")
    os.replace(temporary, inbox)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="report_issue.py")
    parser.add_argument("--session")
    parser.add_argument("--unread", action="store_true")
    parser.add_argument("command")
    parser.add_argument("values", nargs="*")
    args = parser.parse_args(argv)
    feedback_dir = Path(os.environ.get("FEEDBACK_DIR", "~/.claude/feedback")).expanduser()
    feedback_dir.mkdir(parents=True, exist_ok=True)
    inbox = feedback_dir / "inbox.jsonl"

    if args.command == "claim" and len(args.values) == 1:
        (feedback_dir / "owner").write_text(args.values[0], encoding="utf-8")
        return 0
    if args.command == "list":
        if args.values:
            return 64
        for entry in _entries(inbox):
            if args.unread and entry.get("read"):
                continue
            sys.stdout.write(
                f"{entry.get('ts')}\t{entry.get('session')}\t{entry.get('category')}\t"
                f"{entry.get('text', '')[:100]}\n"
            )
        return 0
    if args.command == "ack" and len(args.values) == 1 and args.values[0].isdigit():
        target = int(args.values[0])
        if target < 1:
            return 64
        entries = _entries(inbox)
        unread = [entry for entry in entries if not entry.get("read")]
        if target > len(unread):
            return 64
        unread[target - 1]["read"] = True
        _write_entries(inbox, entries)
        return 0
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
