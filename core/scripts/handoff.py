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
from datetime import datetime, timedelta, timezone
from difflib import unified_diff
from pathlib import Path

# user_log.py and drift_report.py sit next to this file in both the repo and the installed layout.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import user_log
from drift_report import METRICS_NAME, REVIEW_CYCLE_NAME, REVIEW_DONE_NAME, _drift_state_dir

USAGE = "usage: handoff.py <STATE.md> <session-name> [<cwd>] [--transcript <path>] [--dry-run]"
POLL_INTERVAL_SECONDS = 1
START_TIMEOUT_SECONDS = 20
STATE_MAX_AGE_SECONDS = 120
ASK_REGISTER_CHECK_TIMEOUT_SECONDS = 10
ASK_REGISTER_REASON_LINES = 10
GOAL_HEADING = "## Goal and standing rules"
QUESTIONS_HEADING = "## Open questions to the user"
NEXT_HEADING = "## Next"
REQUIRED_HEADINGS = (GOAL_HEADING, QUESTIONS_HEADING)
CHECKPOINT_NAME = ".handoff-checkpoint.json"
USER_LOG_NAME = "user-log.md"
MATCH_PREFIX_CHARS = 60
MIN_CANDIDATE_CHARS = 12
SHOWN_UNREFLECTED_LIMIT = 10
MATCH_QUOTES = str.maketrans({"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"'})
LIST_MARKER = re.compile(r"^\s*(?:[-*\u2022]|\d+[.)])\s+")
SENTENCE_END = re.compile(r"(?<=[.?!])\s+")
REVIEW_LAUNCH_COUNT = 10
REVIEW_AGE_DAYS = 21
REVIEW_REMINDER = (
    "Drift-fix review due: run `python3 ~/.claude/scripts/drift_report.py`, "
    "then `python3 ~/.claude/scripts/drift_report.py --mark-reviewed`"
)
LOG_HEADER = re.compile(r"^### (\S+) (\S+) (\S+) (\S+)(.*)$")
RESEND_LABEL = re.compile(r"\(resend of ([^)\s]+)\)")
ANSWERED_QUESTION = re.compile(r"^- \[answered[^\]]*\]\s*(.*?)(?:\s+->\s+.*)?$")
METRIC_COUNT_KEYS = (
    "log_entries_since_last",
    "unreflected",
    "open_questions",
    "answered_questions",
    "goal_changed",
    "mow_candidates",
)
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


def _write_handoff_marker(session_name: str, state_path: Path, pids: set[int]) -> None:
    """Tell context_guard.py this session already started its successor."""
    session_id = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    if not session_id:
        sys.stderr.write("handoff.py: CLAUDE_CODE_SESSION_ID unset; no handoff marker written\n")
        return
    state_dir = Path(
        os.environ.get("CONTEXT_GUARD_STATE_DIR")
        or os.path.expanduser("~/.claude/hooks/state/context-guard")
    )
    marker = {
        "successor": session_name,
        "state": str(state_path.resolve()),
        "pids": sorted(pids),
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / f"{session_id}.handoff").write_text(json.dumps(marker))
    except OSError as error:
        sys.stderr.write(f"handoff.py: failed to write handoff marker: {error}\n")


def _ask_register_projects() -> list[Path]:
    try:
        layers_root = Path(os.environ.get("AISETUP_LAYERS_ROOT", "~/.ai-setup")).expanduser()
        # A relative root would read profile.json from whatever folder handoff.py was called from.
        if not layers_root.is_absolute():
            return []
        profile = json.loads((layers_root / "profile.json").read_text(encoding="utf-8"))
    except (OSError, RuntimeError, ValueError):
        return []
    if not isinstance(profile, dict):
        return []
    entries = profile.get("ask_register_projects")
    if not isinstance(entries, list) or not all(isinstance(entry, str) for entry in entries):
        return []
    projects = []
    for entry in entries:
        try:
            path = Path(entry).expanduser()
            # A relative entry would resolve against whatever folder handoff.py was called from.
            if path.is_absolute():
                projects.append(path.resolve())
        except (OSError, RuntimeError, ValueError):
            continue
    return projects


def _ask_register_refusal(state_path: Path, cwd: Path) -> str | None:
    """Return the refusal text when a listed project's ask register has unsorted messages."""
    projects = _ask_register_projects()
    project = None
    for folder in (cwd, state_path.parent):
        try:
            folder = folder.resolve()
        except (OSError, RuntimeError, ValueError):
            continue
        project = next((item for item in projects if folder.is_relative_to(item)), None)
        if project is not None:
            break
    if project is None:
        return None
    script = project / "scripts" / "asks.py"
    # Path.is_file() raises PermissionError on Python 3.12 when scripts/ cannot be searched.
    if not os.path.isfile(script):
        sys.stderr.write(f"handoff.py: ask register not checked: {script} not found\n")
        return None
    try:
        result = subprocess.run(
            [sys.executable, str(script), "check"],
            cwd=project,
            check=False,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=ASK_REGISTER_CHECK_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        sys.stderr.write(
            "handoff.py: ask register not checked: check timed out after "
            f"{ASK_REGISTER_CHECK_TIMEOUT_SECONDS} seconds\n"
        )
        return None
    except OSError as error:
        sys.stderr.write(f"handoff.py: ask register not checked: check failed to start: {error}\n")
        return None
    # Python exits 1 on an uncaught error, so only 3 refuses; a broken script must not block.
    if result.returncode == 3:
        reason = result.stdout.splitlines()[:ASK_REGISTER_REASON_LINES]
        return "\n".join(
            [
                "handoff.py: ask register has unsorted messages; "
                "sort them, rewrite STATE.md, then rerun handoff.py",
                *reason,
            ]
        ) + "\n"
    if result.returncode:
        sys.stderr.write(
            f"handoff.py: ask register not checked: check exited {result.returncode}\n"
        )
    return None


@dataclass
class LogEntry:
    key: str
    channel: str
    text: str
    resend_of: str | None


def _normalise(text: str) -> str:
    return " ".join(text.split())


def _match_normalise(text: str) -> str:
    return _normalise(text).casefold().translate(MATCH_QUOTES)


def _match_needles(text: str) -> list[str]:
    """Return the prefixes of each line and sentence of `text` long enough to match on their own."""
    needles = []
    for line in text.splitlines():
        for piece in SENTENCE_END.split(LIST_MARKER.sub("", line)):
            piece = _match_normalise(piece)
            if len(piece) >= MIN_CANDIDATE_CHARS:
                needles.append(piece[:MATCH_PREFIX_CHARS])
    if needles:
        return needles
    whole = _match_normalise(text)[:MATCH_PREFIX_CHARS]
    return [whole] if whole else []


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


def _same_entry(key: str, reference: str) -> bool:
    """A log header carries a short uuid while a resend label may carry the full one."""
    return key.startswith(reference) or reference.startswith(key)


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


def _goal_change_report(goal_lines: list[str], checkpoint: dict, record: dict) -> str | None:
    """Return a diff of the Goal section against the previous handoff's snapshot; never refuses."""
    snapshot = checkpoint.get("goal_snapshot")
    if not isinstance(snapshot, list):
        return None
    record["goal_changed"] = snapshot != goal_lines
    if not record["goal_changed"]:
        return None
    diff = unified_diff(
        snapshot, goal_lines, "goal at previous handoff", "goal now", lineterm=""
    )
    return (
        "handoff.py: the Goal and standing rules section changed since the previous handoff; "
        "check that no rule was paraphrased or dropped:\n" + "\n".join(diff) + "\n"
    )


def _unreflected_messages_warning(
    entries: list[LogEntry] | None,
    checkpoint: dict,
    state_text: str,
    run_dir: Path,
    record: dict,
) -> str | None:
    """Return one line naming log entries since the previous handoff that STATE.md lacks."""
    if entries is None:
        sys.stderr.write(
            "handoff.py: user messages not checked: log not synced\n"
        )
        return None
    seen = set(checkpoint.get("user_log_uuids_seen") or [])
    since = [entry for entry in entries if entry.key not in seen]
    record["log_entries_since_last"] = len(since)
    state_haystack = _match_normalise(state_text)
    try:
        decisions = (run_dir / "decisions.md").read_text(encoding="utf-8", errors="replace")
    except OSError:
        decisions = ""
    full_haystack = state_haystack + " " + _match_normalise(decisions)
    unreflected = []
    for index, entry in enumerate(since):
        later = since[index + 1 :]
        # Only the latest message of a resend chain has to be recorded.
        if any(item.resend_of and _same_entry(entry.key, item.resend_of) for item in later):
            continue
        if entry.channel == "ask":
            answers = [line[2:] for line in entry.text.splitlines() if line.startswith("A:")]
            needles = _match_needles("\n".join(answers))
            haystack = state_haystack
        else:
            needles = _match_needles(entry.text)
            haystack = full_haystack
        if needles and not any(needle in haystack for needle in needles):
            unreflected.append(entry)
    record["unreflected"] = len(unreflected)
    if not unreflected:
        return None
    shown = [
        f'{entry.key[:8]} "{_normalise(entry.text)[:MATCH_PREFIX_CHARS]}"'
        for entry in unreflected[:SHOWN_UNREFLECTED_LIMIT]
    ]
    more = len(unreflected) - len(shown)
    suffix = f" | and {more} more in {USER_LOG_NAME}" if more else ""
    return f"Check these were recorded in STATE.md: {' | '.join(shown)}{suffix}"


def _mow_list(sections: dict[str, list[str]], checkpoint: dict, record: dict) -> str | None:
    """Return answered questions kept for a full handoff and DONE Next items; never edits."""
    seen = set(checkpoint.get("answered_questions_seen") or [])
    stale = [question for question in _answered_questions(sections) if question in seen]
    done = [
        line.strip()
        for line in sections.get(NEXT_HEADING, [])
        if re.search(r"\bDONE\b", line)
    ]
    record["mow_candidates"] = len(stale) + len(done)
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
        if isinstance(value, bool):
            return "yes" if value else "no"
        return str(value)

    return (
        f"Drift check: {show('log_entries_since_last')} user-log entries since the previous "
        f"handoff, {show('unreflected')} unreflected, {show('open_questions')} open and "
        f"{show('answered_questions')} answered questions, goal changed: {show('goal_changed')}."
    )


def _advance_checkpoint(
    run_dir: Path,
    checkpoint: dict,
    entries: list[LogEntry] | None,
    answered: list[str],
    goal_lines: list[str],
) -> None:
    seen = set(checkpoint.get("user_log_uuids_seen") or [])
    seen.update(entry.key for entry in entries or [])
    data = {
        "last_handoff_ts": datetime.now(timezone.utc).isoformat(),
        "user_log_uuids_seen": sorted(seen),
        "answered_questions_seen": answered,
        "goal_snapshot": goal_lines,
    }
    path = run_dir / CHECKPOINT_NAME
    temporary = path.with_suffix(".tmp")
    try:
        temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
        temporary.replace(path)
    except OSError as error:
        sys.stderr.write(f"handoff.py: failed to write {path}: {error}\n")


def _write_metrics(run_dir: Path | None, session_name: str, record: dict) -> None:
    line = json.dumps(
        {
            "ts": datetime.now(timezone.utc).isoformat(),
            "run_dir": str(run_dir) if run_dir else None,
            "session": session_name,
            **record,
        }
    )
    targets = [_drift_state_dir() / METRICS_NAME]
    if run_dir is not None:
        targets.append(run_dir / METRICS_NAME)
    for target in targets:
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except OSError as error:
            sys.stderr.write(f"handoff.py: failed to write drift metrics to {target}: {error}\n")


def _review_reminder() -> str | None:
    state_dir = _drift_state_dir()
    if (state_dir / REVIEW_DONE_NAME).exists():
        return None
    try:
        cycle_start = datetime.fromisoformat(
            (state_dir / REVIEW_CYCLE_NAME).read_text(encoding="utf-8").strip()
        )
    except (OSError, ValueError):
        cycle_start = None
    try:
        lines = (state_dir / METRICS_NAME).read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    launched = 0
    first_ts = None
    for line in lines:
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if not isinstance(item, dict):
            continue
        if cycle_start is not None:
            # A naive or malformed ts raises TypeError or ValueError; such lines are kept.
            try:
                before_cycle = datetime.fromisoformat(item.get("ts")) < cycle_start
            except (TypeError, ValueError):
                before_cycle = False
            if before_cycle:
                continue
        if first_ts is None and isinstance(item.get("ts"), str):
            first_ts = item["ts"]
        if item.get("outcome") == "launched":
            launched += 1
    due = launched >= REVIEW_LAUNCH_COUNT
    if not due and first_ts:
        try:
            first = datetime.fromisoformat(first_ts)
        except ValueError:
            first = None
        if first is not None and first.tzinfo is not None:
            due = datetime.now(timezone.utc) - first >= timedelta(days=REVIEW_AGE_DAYS)
    return REVIEW_REMINDER if due else None


def handoff(
    state_path: Path,
    session_name: str,
    cwd: Path,
    transcript: Path | None = None,
    dry_run: bool = False,
) -> int:
    record: dict = {"outcome": "error", **dict.fromkeys(METRIC_COUNT_KEYS)}
    run_dir = state_path.parent if state_path.is_file() else None
    try:
        return _run_handoff(state_path, session_name, cwd, transcript, dry_run, record)
    finally:
        _write_metrics(run_dir, session_name, record)
        reminder = _review_reminder()
        if reminder:
            sys.stdout.write(f"{reminder}\n")


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
        record["outcome"] = "refused:missing-state"
        return 1
    age = time.time() - state_path.stat().st_mtime
    if age > STATE_MAX_AGE_SECONDS:
        sys.stderr.write(
            f"handoff.py: STATE.md is {int(age)}s old (limit {STATE_MAX_AGE_SECONDS}s); "
            "rewrite it, then rerun handoff.py in a later tool call\n"
        )
        record["outcome"] = "refused:stale-state"
        return 1
    refusal = _ask_register_refusal(state_path, cwd)
    if refusal:
        sys.stderr.write(refusal)
        record["outcome"] = "refused:ask-register"
        return 3
    try:
        state_text = state_path.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        sys.stderr.write(f"handoff.py: failed to read STATE.md: {error}\n")
        record["outcome"] = "refused:missing-state"
        return 1
    sections = _sections(state_text)
    refusal = _required_sections_refusal(sections)
    if refusal:
        sys.stderr.write(refusal)
        record["outcome"] = "refused:sections"
        return 1
    question_bullets = _bullets(sections[QUESTIONS_HEADING])
    record["open_questions"] = sum(bullet.startswith("- [open]") for bullet in question_bullets)
    record["answered_questions"] = sum(
        bullet.startswith("- [answered") for bullet in question_bullets
    )
    run_dir = state_path.parent
    synced = _user_log_sync(run_dir, transcript)
    checkpoint = _load_checkpoint(run_dir)
    goal_lines = [line.strip() for line in sections[GOAL_HEADING] if line.strip()]
    entries = _read_user_log(run_dir) if synced else None
    goal_report = _goal_change_report(goal_lines, checkpoint, record)
    if goal_report:
        sys.stdout.write(goal_report)
    check_line = _unreflected_messages_warning(entries, checkpoint, state_text, run_dir, record)
    if check_line:
        sys.stdout.write(f"handoff.py: {check_line}\n")
    mow = _mow_list(sections, checkpoint, record)
    if mow:
        sys.stdout.write(mow)
    prompt = (
        f"Read {state_path} and continue from it. "
        "Read only that file to start; it points at everything else. "
        + _summary_line(record)
    )
    if record.get("unreflected"):
        prompt += (
            f" {record['unreflected']} user-log entries may be missing from STATE.md; "
            f"compare {(run_dir / USER_LOG_NAME).resolve()} with STATE.md."
        )
    if dry_run:
        sys.stdout.write(f"dry run: nothing launched; successor prompt:\n{prompt}\n")
        record["outcome"] = "dry-run"
        return 0
    record["outcome"] = "failed:launch"
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
    _write_handoff_marker(session_name, state_path, new_pids)
    _advance_checkpoint(
        run_dir, checkpoint, entries, _answered_questions(sections), goal_lines
    )
    record["outcome"] = "launched"
    sys.stdout.write(f"session: {session_name}\n")
    sys.stdout.write(f"state:   {state_path}\n")
    return 0


def main(argv: list[str] | None = None) -> int:
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
