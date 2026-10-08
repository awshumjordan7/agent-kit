from __future__ import annotations

import json
import re
from pathlib import Path

STATE_PATH_PATTERN = re.compile(r"(?:~|/)[^\s'\"`<>]*STATE\.md")
# Harness-generated user turns start with a tag such as <task-notification> or <command-name>.
HARNESS_PREFIX = "<"


def _message_text(entry: dict) -> str | None:
    """Return the text of a genuine user turn, or None for any other transcript line."""
    if entry.get("type") != "user" or entry.get("isMeta") or entry.get("isSidechain"):
        return None
    origin = entry.get("origin")
    if isinstance(origin, dict) and origin.get("kind") not in {None, "human"}:
        return None
    message = entry.get("message")
    if not isinstance(message, dict):
        return None
    content = message.get("content")
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        if any(isinstance(block, dict) and block.get("type") == "tool_result" for block in content):
            return None
        text = "\n".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    else:
        return None
    text = text.strip()
    if not text or text.startswith(HARNESS_PREFIX):
        return None
    return text


def first_user_message(transcript_path: Path) -> str | None:
    try:
        with transcript_path.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                if isinstance(entry, dict):
                    text = _message_text(entry)
                    if text is not None:
                        return text
    except OSError:
        return None
    return None


def resolve_run_dir(cwd: Path | str | None, transcript_path: Path | str | None) -> Path | None:
    """Return the dir of a STATE.md named in the first user message, else of <cwd>/STATE.md."""
    if transcript_path:
        text = first_user_message(Path(transcript_path))
        if text:
            for match in STATE_PATH_PATTERN.finditer(text):
                candidate = Path(match.group(0)).expanduser()
                try:
                    if candidate.is_file():
                        return candidate.resolve().parent
                except OSError:
                    continue
    if cwd:
        try:
            state = Path(cwd) / "STATE.md"
            if state.is_file():
                return state.resolve().parent
        except OSError:
            return None
    return None
