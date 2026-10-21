from __future__ import annotations

import json
import os
import plistlib
import re
import shlex
import shutil
import subprocess
import sys
import time
import xml.parsers.expat
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

# user_log.py sits next to this file in both the repo and the installed layout.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import user_log

USAGE = "usage: handoff.py <STATE.md> <session-name> [<cwd>] [--transcript <path>] [--dry-run]"
POLL_INTERVAL_SECONDS = 1
START_TIMEOUT_SECONDS = 20
STATE_MAX_AGE_SECONDS = 120
STATE_SIZE_WARN_BYTES = 30 * 1024
ARCHIVE_NAME = "STATE-archive.md"
GOAL_HEADING = "## Goal and standing rules"
QUESTIONS_HEADING = "## Open questions to the user"
NEXT_HEADING = "## Next"
REQUIRED_HEADINGS = (GOAL_HEADING, QUESTIONS_HEADING)
CHECKPOINT_NAME = ".handoff-checkpoint.json"
USER_LOG_NAME = "user-log.md"
SANDBOX_STOP = (
    "handoff.py must run outside the Bash sandbox, and this call ran inside it. "
    "Run it again as one bare Bash call spelled exactly python3 ~/.claude/scripts/handoff.py <args>: "
    "no cd prefix, pipe, redirect, 2>&1, ';' or '&&', with the ~/.claude path as written."
)
LOG_HEADER = re.compile(r"^### (\S+) (\S+) (\S+) (\S+)(.*)$")
RESEND_LABEL = re.compile(r"\(resend of ([^)\s]+)\)")
ANSWERED_QUESTION = re.compile(r"^- \[answered[^\]]*\]\s*(.*?)(?:\s+->\s+.*)?$")
NEXT_ENTRY_START = re.compile(r"^([0-9A-Za-z]+)[.)] ")
SUPERSEDED_TAG = "(superseded by "
APPLESCRIPT = """
on run argv
    set cwd to item 1 of argv
    set inputText to item 2 of argv
    tell application "Ghostty"
        if (count of windows) is 0 then error "Ghostty has no window"
        set win to front window
        set cfg to {command:"/bin/zsh", initial working directory:cwd, initial input:(inputText & return)}
        new tab in win with configuration cfg
    end tell
end run
"""


def _claude_pids(session_name: str) -> set[int]:
    pattern = rf"(^|/)claude --name {re.escape(session_name)}( |$)"
    result = subprocess.run(
        ["pgrep", "-f", pattern],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode not in {0, 1}:
        raise OSError(result.stderr.strip() or "pgrep failed")
    return {int(pid) for pid in result.stdout.split()}


def _screen_locked() -> bool:
    try:
        result = subprocess.run(
            ["ioreg", "-n", "Root", "-d1", "-a"], check=False, capture_output=True
        )
    except FileNotFoundError:
        return False
    if result.returncode:
        return False
    try:
        root = plistlib.loads(result.stdout)
    except (plistlib.InvalidFileException, xml.parsers.expat.ExpatError):
        return False
    if not isinstance(root, dict):
        return False
    return any(
        isinstance(user, dict) and user.get("CGSSessionScreenIsLocked")
        for user in root.get("IOConsoleUsers", [])
    )


def _open_ghostty_tab(cwd: Path, input_text: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["osascript", "-", str(cwd), input_text],
        input=APPLESCRIPT,
        check=False,
        capture_output=True,
        text=True,
    )


def _open_windows_terminal_tab(
    state_path: Path, session_name: str, cwd: Path, prompt: str, distro: str
) -> subprocess.CompletedProcess[str]:
    script = state_path.parent / f"handoff-{session_name}.sh"
    # wt.exe splits its command line on ";" and the prompt contains one.
    script.write_text(
        "#!/usr/bin/env bash\n"
        f"cd {shlex.quote(str(cwd))} || exit 1\n"
        f"claude --name {shlex.quote(session_name)} --permission-mode bypassPermissions {shlex.quote(prompt)}\n"
        "exec bash\n"
    )
    return subprocess.run(
        [
            "wt.exe", "-w", "0", "new-tab", "--title", session_name,
            "wsl.exe", "-d", distro, "--cd", str(cwd), "--", "bash", "-l", str(script),
        ],
        check=False,
        capture_output=True,
        text=True,
    )


@dataclass
class LogEntry:
    key: str
    channel: str
    text: str
    resend_of: str | None


def _normalise(text: str) -> str:
    return " ".join(text.split())


def _sections(state_text: str) -> dict[str, list[str]]:
    """Map each `## ` heading to its lines; `#` and `##` headings end a section, `###` does not."""
    sections: dict[str, list[str]] = {}
    current = None
    for line in state_text.splitlines():
        stripped = line.rstrip()
        if re.match(r"^#{1,2} ", stripped):
            current = stripped if stripped.startswith("## ") else None
            if current is not None:
                sections.setdefault(current, [])
        elif current is not None:
            sections[current].append(stripped)
    return sections


def _is_next_heading(heading: str) -> bool:
    return heading == NEXT_HEADING or heading.startswith(NEXT_HEADING + " ")


def _next_sections(sections: dict[str, list[str]]) -> list[str]:
    """Return every Next heading, including forms such as `## Next (session 14 starts here)`."""
    return [heading for heading in sections if _is_next_heading(heading)]


def _superseded_entries(state_text: str) -> list[tuple[int, int]]:
    """Return [start, end) line ranges of Next entries whose first line carries the superseded tag.

    An entry starts at a column-0 `<id>. ` or `<id>) ` line and runs to the next entry start
    or heading. Lines inside ``` or ~~~ fences never start an entry or end one.
    Indexes count lines as str.splitlines does.
    """
    lines = state_text.splitlines()
    entries: list[tuple[int, int]] = []
    start: int | None = None
    in_next = False
    in_fence = False

    def close(end: int) -> None:
        if start is not None and SUPERSEDED_TAG in lines[start].lower():
            entries.append((start, end))

    for index, line in enumerate(lines):
        if line.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        stripped = line.rstrip()
        if re.match(r"^#+ ", stripped):
            close(index)
            start = None
            if re.match(r"^#{1,2} ", stripped):
                in_next = stripped.startswith("## ") and _is_next_heading(stripped)
        elif in_next and NEXT_ENTRY_START.match(line):
            close(index)
            start = index
    close(len(lines))
    return entries


def _archive_superseded(state_path: Path, state_text: str, dry_run: bool) -> str:
    """Move tagged Next entries to STATE-archive.md and return the STATE.md text left.

    The archive is appended before STATE.md is rewritten, so a failed append loses nothing.
    Lines are cut from the file's own strictly decoded text, so every kept byte is unchanged.
    """
    if not _superseded_entries(state_text):
        return state_text
    try:
        text = state_path.read_bytes().decode("utf-8")
    except OSError as error:
        sys.stderr.write(f"handoff.py: superseded entries not archived: cannot read {state_path}: {error}\n")
        return state_text
    except UnicodeDecodeError as error:
        sys.stderr.write(
            f"handoff.py: superseded entries not archived: {state_path} is not valid UTF-8: {error}\n"
        )
        return state_text
    ranges = _superseded_entries(text)
    if not ranges:
        return state_text
    lines = text.splitlines(keepends=True)
    moved_indexes = {index for start, end in ranges for index in range(start, end)}
    moved = "".join(lines[index] for index in sorted(moved_indexes))
    kept = "".join(line for index, line in enumerate(lines) if index not in moved_indexes)
    moved_bytes = len(moved.encode("utf-8"))
    archive_path = state_path.parent / ARCHIVE_NAME
    if dry_run:
        sys.stdout.write(
            f"handoff.py: would move {len(ranges)} superseded entries ({moved_bytes} bytes) "
            f"to {ARCHIVE_NAME}\n"
        )
        return state_text
    newline = "\r\n" if lines[ranges[0][0]].endswith("\r\n") else "\n"
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    block = f"{newline}## {timestamp} moved from STATE.md by handoff.py{newline}{newline}{moved}"
    if not moved.endswith(("\n", "\r")):
        block += newline
    try:
        with archive_path.open("a", encoding="utf-8", newline="") as archive:
            archive.write(block)
    except OSError as error:
        sys.stderr.write(
            f"handoff.py: superseded entries not archived: failed to append to {archive_path}: "
            f"{error}; STATE.md left unchanged\n"
        )
        return state_text
    temporary = state_path.with_name(state_path.name + ".tmp")
    try:
        temporary.write_bytes(kept.encode("utf-8"))
        temporary.replace(state_path)
    except OSError as error:
        sys.stderr.write(
            f"handoff.py: entries were appended to {archive_path}, but rewriting {state_path} "
            f"failed: {error}; delete the tagged entries from STATE.md by hand\n"
        )
        return state_text
    sys.stdout.write(
        f"handoff.py: moved {len(ranges)} superseded entries ({moved_bytes} bytes) to {archive_path}\n"
    )
    return kept


def _size_warning(state_text: str, sections: dict[str, list[str]]) -> str | None:
    """Return a warning when STATE.md is over STATE_SIZE_WARN_BYTES; never refuses."""
    size = len(state_text.encode("utf-8", errors="replace"))
    if size <= STATE_SIZE_WARN_BYTES:
        return None
    section_bytes = sorted(
        (
            (
                len(heading.encode("utf-8", errors="replace")) + 1
                + sum(len(line.encode("utf-8", errors="replace")) + 1 for line in lines),
                heading,
            )
            for heading, lines in sections.items()
        ),
        reverse=True,
    )
    largest = ", ".join(f"{heading} ({count} bytes)" for count, heading in section_bytes[:2])
    tagged = len(_superseded_entries(state_text))
    return (
        f"handoff.py: STATE.md is {size} bytes, over the {STATE_SIZE_WARN_BYTES}-byte limit. "
        f"Largest sections: {largest or 'none'}. Tagged Next entries left: {tagged}. "
        "Trim it as ~/.claude/references/state-template.md says.\n"
    )


def _bullets(lines: list[str]) -> list[str]:
    return [line.strip() for line in lines if line.lstrip().startswith("- ")]


def _answered_questions(sections: dict[str, list[str]]) -> list[str]:
    questions = []
    for bullet in _bullets(sections.get(QUESTIONS_HEADING, [])):
        match = ANSWERED_QUESTION.match(bullet)
        if match:
            questions.append(_normalise(match.group(1)))
    return questions


def _required_sections_refusal(sections: dict[str, list[str]]) -> str | None:
    """Return the refusal text when a required STATE.md section is missing or has no bullet."""
    missing = [heading for heading in REQUIRED_HEADINGS if not _bullets(sections.get(heading, []))]
    if not missing:
        return None
    return "\n".join(
        [
            "handoff.py: STATE.md lacks required sections (missing heading or no bullet):",
            *(f"  {heading}" for heading in missing),
            "Add each one from the user's own words, quoted verbatim, never paraphrased; "
            "write `- None` under the open questions heading when there are none. "
            "The format is in ~/.claude/references/state-template.md. Then rerun handoff.py.",
        ]
    ) + "\n"


def _load_checkpoint(run_dir: Path) -> dict:
    path = run_dir / CHECKPOINT_NAME
    try:
        checkpoint = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as error:
        sys.stderr.write(f"handoff.py: ignoring unreadable {path}: {error}\n")
        return {}
    return checkpoint if isinstance(checkpoint, dict) else {}


def _read_user_log(run_dir: Path) -> list[LogEntry] | None:
    path = run_dir / USER_LOG_NAME
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return None
    except OSError as error:
        sys.stderr.write(f"handoff.py: failed to read {path}: {error}\n")
        return None
    entries: list[LogEntry] = []
    header: re.Match[str] | None = None
    body: list[str] = []

    def flush() -> None:
        if header is None:
            return
        label = RESEND_LABEL.search(header.group(5))
        lines = list(body)
        while lines and not lines[0].strip():
            lines.pop(0)
        if label is None and lines and RESEND_LABEL.fullmatch(lines[0].strip()):
            label = RESEND_LABEL.fullmatch(lines.pop(0).strip())
        entries.append(
            LogEntry(
                key=header.group(4),
                channel=header.group(3),
                text="\n".join(lines).strip(),
                resend_of=label.group(1) if label else None,
            )
        )

    for line in text.splitlines():
        match = LOG_HEADER.match(line)
        if match:
            flush()
            header = match
            body = []
        elif header is not None:
            body.append(line)
    flush()
    return entries


def _user_log_sync(run_dir: Path, transcript: Path | None) -> bool:
    """Bring user-log.md up to date before the checks read it; warns, never refuses."""
    if transcript is None:
        transcript = user_log.latest_transcript(run_dir)
    if transcript is None:
        sys.stderr.write(
            "handoff.py: user log not synced: no --transcript given and no transcript "
            "synced for this run yet\n"
        )
        return False
    if not transcript.is_file():
        sys.stderr.write(f"handoff.py: user log not synced: transcript not found: {transcript}\n")
        return False
    return user_log.sync(transcript, run_dir) is not None


def _log_entries_since_last(entries: list[LogEntry] | None, checkpoint: dict, record: dict) -> None:
    """Record how many user-log entries the previous handoff had not seen; never refuses."""
    if entries is None:
        sys.stderr.write("handoff.py: user-log entry count not checked: log not synced\n")
        return
    seen = set(checkpoint.get("user_log_uuids_seen") or [])
    record["log_entries_since_last"] = sum(entry.key not in seen for entry in entries)


def _mow_list(sections: dict[str, list[str]], checkpoint: dict) -> str | None:
    """Return answered questions kept for a full handoff and DONE Next items; never edits."""
    seen = set(checkpoint.get("answered_questions_seen") or [])
    stale = [question for question in _answered_questions(sections) if question in seen]
    done = [
        line.strip()
        for heading in _next_sections(sections)
        for line in sections[heading]
        if re.search(r"\bDONE\b", line)
    ]
    if not stale and not done:
        return None
    lines = [
        "handoff.py: Close these in STATE.md "
        "(answered at the previous handoff, or DONE in Next):"
    ]
    lines += [f"  - answered: {question}" for question in stale]
    lines += [f"  - next: {item}" for item in done]
    return "\n".join(lines) + "\n"


def _summary_line(record: dict) -> str:
    def show(key: str) -> str:
        value = record.get(key)
        if value is None:
            return "not checked"
        return str(value)

    return (
        f"Drift check: {show('log_entries_since_last')} user-log entries since the previous "
        f"handoff, {show('open_questions')} open questions."
    )


def _advance_checkpoint(
    run_dir: Path,
    checkpoint: dict,
    entries: list[LogEntry] | None,
    answered: list[str],
) -> None:
    seen = set(checkpoint.get("user_log_uuids_seen") or [])
    seen.update(entry.key for entry in entries or [])
    data = {
        "last_handoff_ts": datetime.now(timezone.utc).isoformat(),
        "user_log_uuids_seen": sorted(seen),
        "answered_questions_seen": answered,
    }
    path = run_dir / CHECKPOINT_NAME
    temporary = path.with_suffix(".tmp")
    try:
        temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
        temporary.replace(path)
    except OSError as error:
        sys.stderr.write(f"handoff.py: failed to write {path}: {error}\n")


def handoff(
    state_path: Path,
    session_name: str,
    cwd: Path,
    transcript: Path | None = None,
    dry_run: bool = False,
) -> int:
    return _run_handoff(state_path, session_name, cwd, transcript, dry_run, record={})


def _run_handoff(
    state_path: Path,
    session_name: str,
    cwd: Path,
    transcript: Path | None,
    dry_run: bool,
    record: dict,
) -> int:
    if not state_path.is_file():
        sys.stderr.write(f"handoff.py: STATE.md not found: {state_path}\n")
        return 1
    age = time.time() - state_path.stat().st_mtime
    if age > STATE_MAX_AGE_SECONDS:
        sys.stderr.write(
            f"handoff.py: STATE.md is {int(age)}s old (limit {STATE_MAX_AGE_SECONDS}s); "
            "rewrite it, then rerun handoff.py in a later tool call\n"
        )
        return 1
    try:
        state_text = state_path.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        sys.stderr.write(f"handoff.py: failed to read STATE.md: {error}\n")
        return 1
    sections = _sections(state_text)
    refusal = _required_sections_refusal(sections)
    if refusal:
        sys.stderr.write(refusal)
        return 1
    state_text = _archive_superseded(state_path, state_text, dry_run)
    sections = _sections(state_text)
    question_bullets = _bullets(sections[QUESTIONS_HEADING])
    record["open_questions"] = sum(bullet.startswith("- [open") for bullet in question_bullets)
    run_dir = state_path.parent
    synced = _user_log_sync(run_dir, transcript)
    checkpoint = _load_checkpoint(run_dir)
    entries = _read_user_log(run_dir) if synced else None
    _log_entries_since_last(entries, checkpoint, record)
    mow = _mow_list(sections, checkpoint)
    if mow:
        sys.stdout.write(mow)
    size_warning = _size_warning(state_text, sections)
    if size_warning:
        sys.stdout.write(size_warning)
    prompt = (
        f"Read {state_path} and continue from it. "
        "Read only that file to start; it points at everything else. "
        + _summary_line(record)
    )
    if dry_run:
        sys.stdout.write(f"dry run: nothing launched; successor prompt:\n{prompt}\n")
        return 0
    input_text = shlex.join(
        ["claude", "--name", session_name, "--permission-mode", "bypassPermissions", prompt]
    )
    manual_command = f"cd {shlex.quote(str(cwd))} && " + shlex.join(
        ["claude", "--name", session_name, "--permission-mode", "bypassPermissions", prompt]
    )
    run_yourself = f"run this command yourself: {manual_command}"
    distro = os.environ.get("WSL_DISTRO_NAME", "")
    on_wsl = sys.platform == "linux" and bool(distro) and shutil.which("wt.exe") is not None
    if sys.platform != "darwin" and not on_wsl:
        sys.stderr.write(f"handoff.py: no terminal tab opener for this platform; {run_yourself}\n")
        return 1
    try:
        existing_pids = _claude_pids(session_name)
    except OSError as error:
        sys.stderr.write(f"handoff.py: failed to inspect Claude processes: {error}\n")
        return 1
    if existing_pids:
        sys.stderr.write(
            f"handoff.py: a claude session named {session_name!r} already runs "
            f"(pids {sorted(existing_pids)}); pick a new name or stop that session\n"
        )
        return 1
    if sys.platform == "darwin":
        if _screen_locked():
            sys.stderr.write(
                "handoff.py: the screen is locked, so Ghostty cannot open a tab; "
                f"unlock the Mac and rerun handoff.py, or {run_yourself}\n"
            )
            return 1
        result = _open_ghostty_tab(cwd, input_text)
        if result.returncode:
            sys.stderr.write(
                f"handoff.py: failed to open Ghostty tab: {result.stderr.strip()}; {run_yourself}\n"
            )
            return 1
    else:
        try:
            result = _open_windows_terminal_tab(state_path, session_name, cwd, prompt, distro)
        except OSError as error:
            sys.stderr.write(
                f"handoff.py: failed to open Windows Terminal tab: {error}; {run_yourself}\n"
            )
            return 1
        if result.returncode:
            sys.stderr.write(
                f"handoff.py: failed to open Windows Terminal tab: {result.stderr.strip()}; "
                f"{run_yourself}\n"
            )
            return 1
    deadline = time.monotonic() + START_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        time.sleep(POLL_INTERVAL_SECONDS)
        try:
            new_pids = _claude_pids(session_name) - existing_pids
            if new_pids:
                break
        except OSError as error:
            sys.stderr.write(f"handoff.py: failed to inspect Claude processes: {error}\n")
            return 1
    else:
        locked = " (the screen is locked)" if sys.platform == "darwin" and _screen_locked() else ""
        sys.stderr.write(
            f"handoff: successor {session_name!r} did not start{locked}; {run_yourself}\n"
        )
        return 1
    _advance_checkpoint(run_dir, checkpoint, entries, _answered_questions(sections))
    sys.stdout.write(f"session: {session_name}\n")
    sys.stdout.write(f"state:   {state_path}\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    # Claude Code sets SANDBOX_RUNTIME only in sandboxed Bash calls; any value counts.
    if "SANDBOX_RUNTIME" in os.environ:
        sys.stderr.write(SANDBOX_STOP + "\n")
        return 86
    argv = sys.argv[1:] if argv is None else argv
    positional: list[str] = []
    transcript = None
    dry_run = False
    arguments = iter(argv)
    for argument in arguments:
        if argument == "--dry-run":
            dry_run = True
        elif argument == "--transcript":
            value = next(arguments, None)
            if value is None:
                sys.stderr.write(f"{USAGE}\n")
                return 64
            transcript = Path(value).expanduser().resolve()
        else:
            positional.append(argument)
    if len(positional) not in {2, 3}:
        sys.stderr.write(f"{USAGE}\n")
        return 64
    cwd = Path(positional[2]).resolve() if len(positional) == 3 else Path.cwd()
    return handoff(Path(positional[0]).resolve(), positional[1], cwd, transcript, dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
