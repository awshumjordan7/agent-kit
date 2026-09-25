from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

USAGE = "usage: handoff.py <STATE.md> <session-name> [<cwd>]"
POLL_INTERVAL_SECONDS = 1
START_TIMEOUT_SECONDS = 20
STATE_DIR = Path(
    os.environ.get("CONTEXT_GUARD_STATE_DIR")
    or os.path.expanduser("~/.claude/hooks/state/context-guard")
)
SESSION_ID_SHAPE = re.compile(r"[\w-]+")
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


def _write_successor_marker(session_name: str, state_path: Path) -> None:
    """context_guard.py reads this marker to skip its 340k Stop block while the successor runs."""
    session_id = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    if not SESSION_ID_SHAPE.fullmatch(session_id):
        return
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        (STATE_DIR / f"{session_id}.successor").write_text(f"{session_name}\n{state_path}\n")
    except OSError as error:
        sys.stderr.write(f"handoff.py: could not write the successor marker: {error}\n")


def handoff(state_path: Path, session_name: str, cwd: Path) -> int:
    if not state_path.is_file():
        sys.stderr.write(f"handoff.py: STATE.md not found: {state_path}\n")
        return 1
    prompt = (
        f"Read {state_path} and continue from it. "
        "Read only that file to start; it points at everything else."
    )
    input_text = f"claude --name {session_name!r} --permission-mode bypassPermissions {prompt!r}"
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
    if sys.platform == "darwin":
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
            if _claude_pids(session_name) - existing_pids:
                break
        except OSError as error:
            sys.stderr.write(f"handoff.py: failed to inspect Claude processes: {error}\n")
            return 1
    else:
        sys.stderr.write(f"handoff: successor {session_name!r} did not start; {run_yourself}\n")
        return 1
    _write_successor_marker(session_name, state_path)
    sys.stdout.write(f"session: {session_name}\n")
    sys.stdout.write(f"state:   {state_path}\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) not in {2, 3}:
        sys.stderr.write(f"{USAGE}\n")
        return 64
    cwd = Path(argv[2]).resolve() if len(argv) == 3 else Path.cwd()
    return handoff(Path(argv[0]).resolve(), argv[1], cwd)


if __name__ == "__main__":
    raise SystemExit(main())
