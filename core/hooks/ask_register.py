from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

SYNC_TIMEOUT_SECONDS = 6
AGENDA_TIMEOUT_SECONDS = 3
MAX_LINES = 40
MAX_LINE_CHARS = 200
# Claude Code cuts a hook's output to a short preview above about 10,000 characters.
MAX_TOTAL_CHARS = 8000


def listed_projects() -> list[Path]:
    layers_root = Path(os.environ.get("AISETUP_LAYERS_ROOT", "~/.ai-setup")).expanduser()
    try:
        profile = json.loads((layers_root / "profile.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
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
            # A relative entry would resolve against whatever folder the session started in.
            if path.is_absolute():
                projects.append(path.resolve())
        except (OSError, RuntimeError, ValueError):
            continue
    return projects


def match_project(folder: Path) -> Path | None:
    try:
        folder = folder.resolve()
    except (OSError, RuntimeError, ValueError):
        return None
    for project in listed_projects():
        if folder.is_relative_to(project):
            return project
    return None


def _say(line: str) -> int:
    sys.stdout.write(line + "\n")
    sys.stdout.flush()
    return len(line) + 1


def _run(project: Path, command: str, timeout: int) -> tuple[str, str]:
    """Return the command's stdout and, when it failed, the cause."""
    try:
        result = subprocess.run(
            [sys.executable, str(project / "scripts" / "asks.py"), command],
            cwd=project,
            check=False,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return "", f"{command} timed out after {timeout} seconds"
    except OSError as error:
        return "", f"{command} failed to start: {error}"
    if result.returncode:
        return "", f"{command} exited {result.returncode}"
    return result.stdout, ""


def _print_agenda(agenda: str, used: int) -> None:
    lines = [line[:MAX_LINE_CHARS] for line in agenda.splitlines()]
    shown: list[str] = []
    total = used
    for line in lines[:MAX_LINES]:
        if total + len(line) + 1 > MAX_TOTAL_CHARS:
            break
        shown.append(line)
        total += len(line) + 1

    def closing() -> str:
        return f"ask register: {len(lines) - len(shown)} more lines not shown"

    while shown and len(shown) < len(lines) and total + len(closing()) + 1 > MAX_TOTAL_CHARS:
        total -= len(shown.pop()) + 1
    for line in shown:
        _say(line)
    if len(shown) < len(lines):
        _say(closing())


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError, OSError):
        payload = {}
    cwd = payload.get("cwd") if isinstance(payload, dict) else None
    try:
        folder = Path(cwd) if isinstance(cwd, str) and cwd else Path.cwd()
    except OSError:
        return 0
    project = match_project(folder)
    if project is None:
        return 0
    script = project / "scripts" / "asks.py"
    if not script.is_file():
        _say(f"ask register: {script} not found")
        return 0
    used = 0
    _, cause = _run(project, "sync", SYNC_TIMEOUT_SECONDS)
    if cause:
        used += _say(f"ask register: {cause}")
    agenda, cause = _run(project, "agenda", AGENDA_TIMEOUT_SECONDS)
    if cause:
        _say(f"ask register: {cause}")
        return 0
    _print_agenda(agenda, used)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
