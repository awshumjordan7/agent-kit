"""Append the user's own messages from a Claude Code transcript to <run-dir>/user-log.md.

usage: user_log.py sync --transcript <path> --run-dir <dir> [--session <id>]

Captures typed user turns, messages sent mid-turn, and AskUserQuestion answers, verbatim
after secret redaction. Harness turns (tool results, task notifications, cross-session
messages, system reminders), resume prompts, and sessions started with a `GOAL:` prompt
are left out. Re-syncs read from the last byte offset and never write an entry twice.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import re
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

LOG_NAME = "user-log.md"
OFFSETS_NAME = ".user-log.offsets.json"
SESSIONS_NAME = ".user-log.sessions.json"
LOCK_NAME = ".user-log.lock"
LOG_TITLE = (
    "# User log\n\n"
    "The user's messages, verbatim except for redacted secrets. "
    "Appended by user_log.py; do not edit.\n"
)
QUEUE_MATCH_SECONDS = 60
RESEND_WINDOW_SECONDS = 600
RESEND_RATIO = 0.9
RECENT_LIMIT = 20
PENDING_LIMIT = 50
GOAL_PREFIX = "GOAL:"
INTERRUPT_PREFIX = "[Request interrupted"
# Harness-generated user turns start with one of these tags.
HARNESS_TAG = re.compile(
    r"^<(?:task-notification|cross-session-message|command-name|command-message|command-args"
    r"|local-command-stdout|local-command-stderr|local-command-caveat|bash-input|bash-stdout"
    r"|bash-stderr|user-prompt-submit-hook)\b"
)
RESUME_PROMPT = re.compile(r"^Read \S*STATE\.md and continue from it\b")
SYSTEM_REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)
# handoff.py starts a new log entry at any line shaped like an entry header.
HEADER_LIKE = re.compile(r"^(?=### )", re.M)

REDACTED = "[REDACTED]"
SECRET_PATTERNS = (
    re.compile(r"\b(?:sk|pk|rk)[-_][\w-]{12,}"),
    re.compile(r"\b(?:ghp|gho|ghs|ghu|github_pat)_\w{16,}"),
    re.compile(r"\bxox[abpr]-[\w-]{10,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\beyJ[\w-]+\.eyJ[\w-]+(?:\.[\w-]+)?"),
)
ASSIGNED_SECRET = re.compile(
    r"(?i)\b((?:password|passwd|secret|token|api[_-]?key)\s*[:=]\s*)"
    r"(?:\"[^\"\n]*\"?|'[^'\n]*'?|[^\s'\"]+)"
)
LONG_TOKEN = re.compile(r"[A-Za-z0-9_+/=-]{32,}")


def redact(text: str) -> str:
    for pattern in SECRET_PATTERNS:
        text = pattern.sub(REDACTED, text)
    text = ASSIGNED_SECRET.sub(lambda match: match.group(1) + REDACTED, text)

    def long_token(match: re.Match[str]) -> str:
        token = match.group(0)
        # Hex ids, uuids and absolute paths are long but not secret.
        if re.fullmatch(r"[0-9a-f-]+", token) or token.startswith("/"):
            return token
        mixed = (
            re.search(r"[a-z]", token) and re.search(r"[A-Z]", token) and re.search(r"\d", token)
        )
        if not mixed:
            return token
        if "-" in token and all(len(segment) < 20 for segment in token.split("-")):
            return token
        return REDACTED

    return LONG_TOKEN.sub(long_token, text)


@dataclass
class Entry:
    ident: str
    key: str
    ts: str
    session: str
    channel: str
    text: str
    resend_of: str | None = None

    def render(self) -> str:
        label = f" (resend of {self.resend_of})" if self.resend_of else ""
        # A body line that looks like a header would split the entry when handoff.py reads it.
        body = HEADER_LIKE.sub("\\\\", self.text)
        return f"### {self.ts} {self.session[:8]} {self.channel} {self.key}{label}\n{body}\n\n"


def _epoch(ts: object) -> float | None:
    if not isinstance(ts, str):
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _content_text(content: object) -> str | None:
    """Join the text blocks of a message without system reminders; None for tool results."""
    if isinstance(content, str):
        parts = [content]
    elif isinstance(content, list):
        if any(isinstance(block, dict) and block.get("type") == "tool_result" for block in content):
            return None
        parts = [
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        ]
    else:
        return None
    cleaned = [SYSTEM_REMINDER.sub("", part).strip() for part in parts if isinstance(part, str)]
    return "\n".join(part for part in cleaned if part)


def _is_human_text(text: str | None) -> bool:
    return bool(text) and not HARNESS_TAG.match(text) and not text.startswith(INTERRUPT_PREFIX)


def _user_text(line: dict) -> str | None:
    if line.get("type") != "user" or line.get("isMeta") or line.get("isSidechain"):
        return None
    origin = line.get("origin")
    if isinstance(origin, dict) and origin.get("kind") not in {None, "human"}:
        return None
    message = line.get("message")
    if not isinstance(message, dict):
        return None
    text = _content_text(message.get("content"))
    return text if _is_human_text(text) else None


def _midturn_text(line: dict) -> str | None:
    attachment = line.get("attachment")
    if line.get("type") != "attachment" or not isinstance(attachment, dict):
        return None
    if attachment.get("type") != "queued_command" or attachment.get("isMeta"):
        return None
    if line.get("isSidechain") or attachment.get("commandMode") not in {None, "prompt"}:
        return None
    origin = attachment.get("origin")
    if isinstance(origin, dict) and origin.get("kind") != "human":
        return None
    text = _content_text(attachment.get("prompt"))
    return text if _is_human_text(text) else None


def _ask_answers(line: dict) -> list[str]:
    if line.get("type") != "user" or line.get("isSidechain"):
        return []
    result = line.get("toolUseResult")
    if not isinstance(result, dict) or not isinstance(result.get("answers"), dict):
        return []
    return [
        f"Q: {question}\nA: {answer}"
        for question, answer in result["answers"].items()
        if isinstance(question, str) and isinstance(answer, str)
    ]


class Sync:
    """One pass over the unread part of a transcript, under the run dir's lock."""

    def __init__(self, transcript: Path, state: dict) -> None:
        self.transcript = transcript
        for name in ("sessions", "transcripts"):
            if not isinstance(state.get(name), dict):
                state[name] = {}
        self.sessions: dict[str, str] = state["sessions"]
        transcripts = state["transcripts"]
        if not isinstance(transcripts.get(str(transcript)), dict):
            transcripts[str(transcript)] = {}
        self.own = transcripts[str(transcript)]
        for name in ("ids", "pending", "recent"):
            if not isinstance(self.own.get(name), list):
                self.own[name] = []
        for name in ("offset", "line", "written"):
            if not isinstance(self.own.get(name), int):
                self.own[name] = 0
        for name in ("pending", "recent"):
            self.own[name] = [
                item
                for item in self.own[name]
                if isinstance(item, dict)
                and all(isinstance(item.get(field), str) for field in ("key", "ts", "session", "text"))
            ]
        self.written_ids = {
            ident
            for item in transcripts.values()
            if isinstance(item, dict) and isinstance(item.get("ids"), list)
            for ident in item["ids"]
            if isinstance(ident, str)
        }
        self.entries: list[Entry] = []
        self.parse_errors = 0

    def run(self) -> None:
        offset = self.own["offset"]
        line_number = self.own["line"]
        with self.transcript.open("rb") as handle:
            handle.seek(0, 2)
            if handle.tell() < offset:
                offset, line_number = 0, 0
            handle.seek(offset)
            data = handle.read()
        # The last piece has no newline yet when Claude Code is still writing it.
        *complete, _partial = data.split(b"\n")
        for raw in complete:
            line_number += 1
            offset += len(raw) + 1
            if not raw.strip():
                continue
            try:
                line = json.loads(raw.decode("utf-8", errors="replace"))
            except ValueError:
                self.parse_errors += 1
                continue
            if isinstance(line, dict):
                self._handle(line, line_number)
        self.own["offset"] = offset
        self.own["line"] = line_number

    def _handle(self, line: dict, line_number: int) -> None:
        session = line.get("sessionId") or line.get("session_id") or self.transcript.stem
        if not isinstance(session, str):
            return
        timestamp = line.get("timestamp")
        ts = timestamp if isinstance(timestamp, str) and timestamp.strip() else "-"
        uuid = line.get("uuid") if isinstance(line.get("uuid"), str) else None
        ident = uuid or f"{session}:{line_number}"
        key = uuid[:8] if uuid else f"{session[:8]}:{line_number}"
        if line.get("type") == "queue-operation":
            self._queue_operation(line, session, ts, ident, key)
            return
        text = _user_text(line)
        if text is not None:
            if session not in self.sessions:
                self.sessions[session] = "goal" if text.startswith(GOAL_PREFIX) else "normal"
                if self.sessions[session] == "goal":
                    self.own["goal"] = True
            if self.sessions[session] == "goal" or RESUME_PROMPT.match(text):
                return
            text = redact(text)
            self._drop_pending(session, text, ts, window=None)
            self._add(Entry(ident, key, ts, session, "user", text))
            return
        if self.sessions.get(session) == "goal":
            return
        text = _midturn_text(line)
        if text is not None:
            text = redact(text)
            self._drop_pending(session, text, ts, window=QUEUE_MATCH_SECONDS)
            self._add(Entry(ident, key, ts, session, "midturn", text))
            return
        for index, answer in enumerate(_ask_answers(line), start=1):
            suffix = "" if index == 1 else f".{index}"
            self._add(
                Entry(ident + suffix, key + suffix, ts, session, "ask", redact(answer))
            )

    def _queue_operation(self, line: dict, session: str, ts: str, ident: str, key: str) -> None:
        """Hold a queued message until it shows up as a turn or attachment, or is withdrawn."""
        if self.sessions.get(session) == "goal":
            return
        operation = line.get("operation")
        pending = self.own["pending"]
        if operation == "enqueue":
            text = _content_text(line.get("content"))
            if _is_human_text(text):
                pending.append(
                    {"ident": ident, "key": key, "ts": ts, "session": session, "text": redact(text)}
                )
                del pending[:-PENDING_LIMIT]
        elif operation == "popAll":
            # The user pulled queued messages back to edit them; keep what they first sent.
            for item in [item for item in pending if item["session"] == session]:
                pending.remove(item)
                ident = item["ident"] if isinstance(item.get("ident"), str) else item["key"]
                self._add(Entry(ident, item["key"], item["ts"], session, "midturn", item["text"]))

    def _drop_pending(self, session: str, text: str, ts: str, window: int | None) -> None:
        when = _epoch(ts)
        pending = self.own["pending"]
        for item in pending:
            if item["session"] != session or item["text"] != text:
                continue
            queued = _epoch(item["ts"])
            if window is None or when is None or queued is None or abs(when - queued) <= window:
                pending.remove(item)
                return

    def _add(self, entry: Entry) -> None:
        if entry.ident in self.written_ids:
            return
        when = _epoch(entry.ts)
        recent = self.own["recent"]
        if entry.channel in {"user", "midturn"}:
            if when is not None:
                for earlier in reversed(recent):
                    earlier_when = _epoch(earlier["ts"])
                    if (
                        earlier["session"] == entry.session
                        and earlier_when is not None
                        and 0 <= when - earlier_when <= RESEND_WINDOW_SECONDS
                        and SequenceMatcher(None, earlier["text"], entry.text).ratio()
                        >= RESEND_RATIO
                    ):
                        entry.resend_of = earlier["key"]
                        break
            recent.append(
                {"key": entry.key, "ts": entry.ts, "session": entry.session, "text": entry.text}
            )
            del recent[:-RECENT_LIMIT]
        self.written_ids.add(entry.ident)
        self.own["ids"].append(entry.ident)
        self.own["written"] += 1
        self.entries.append(entry)


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as error:
        sys.stderr.write(f"user_log.py: ignoring unreadable {path}: {error}\n")
        return {}
    return data if isinstance(data, dict) else {}


def _write_json(path: Path, data: dict) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(data, indent=1), encoding="utf-8")
    temporary.replace(path)


@contextmanager
def _locked(run_dir: Path) -> Iterator[None]:
    with (run_dir / LOCK_NAME).open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def sync(transcript: Path, run_dir: Path, session_id: str | None = None) -> int | None:
    """Append new user entries from transcript to the run dir's log.

    Return how many, or None when the sync failed.
    """
    transcript = transcript.expanduser().resolve()
    run_dir = run_dir.expanduser().resolve()
    session_id = session_id or transcript.stem
    try:
        with _locked(run_dir):
            state = _read_json(run_dir / OFFSETS_NAME)
            reader = Sync(transcript, state)
            reader.run()
            log = run_dir / LOG_NAME
            if reader.entries:
                new_log = not log.exists()
                with log.open("a", encoding="utf-8") as handle:
                    if new_log:
                        handle.write(LOG_TITLE + "\n")
                    handle.writelines(entry.render() for entry in reader.entries)
            _write_json(run_dir / OFFSETS_NAME, state)
            sessions = _read_json(run_dir / SESSIONS_NAME)
            sessions[session_id] = {
                "transcript_path": str(transcript),
                "last_sync_ts": datetime.now(timezone.utc).isoformat(),
            }
            _write_json(run_dir / SESSIONS_NAME, sessions)
    except OSError as error:
        sys.stderr.write(f"user_log.py: sync of {transcript} failed: {error}\n")
        return None
    if reader.parse_errors:
        sys.stderr.write(
            f"user_log.py: skipped {reader.parse_errors} unparseable line(s) in {transcript}\n"
        )
    if not reader.own.get("written") and not reader.own.get("goal"):
        sys.stderr.write(f"user_log.py: no user messages found in {transcript} so far\n")
    return len(reader.entries)


def latest_transcript(run_dir: Path) -> Path | None:
    """Return the transcript most recently synced into run_dir, if it still exists."""
    sessions = _read_json(run_dir / SESSIONS_NAME)
    synced = [
        item
        for item in sessions.values()
        if isinstance(item, dict)
        and isinstance(item.get("transcript_path"), str)
        and isinstance(item.get("last_sync_ts"), str)
    ]
    for item in sorted(synced, key=lambda item: item["last_sync_ts"], reverse=True):
        path = Path(item["transcript_path"])
        if path.is_file():
            return path
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="user_log.py")
    commands = parser.add_subparsers(dest="command", required=True)
    sync_parser = commands.add_parser("sync", help="append new user messages to user-log.md")
    sync_parser.add_argument("--transcript", required=True, type=Path)
    sync_parser.add_argument("--run-dir", required=True, type=Path)
    sync_parser.add_argument("--session", help="session id (default: the transcript file name)")
    arguments = parser.parse_args(argv)
    if not arguments.transcript.expanduser().is_file():
        sys.stderr.write(f"user_log.py: transcript not found: {arguments.transcript}\n")
        return 1
    if not arguments.run_dir.expanduser().is_dir():
        sys.stderr.write(f"user_log.py: run dir not found: {arguments.run_dir}\n")
        return 1
    count = sync(arguments.transcript, arguments.run_dir, arguments.session)
    if count is None:
        return 1
    sys.stdout.write(f"user_log.py: {count} new entries\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
