from __future__ import annotations

import subprocess
import sys
from pathlib import Path

USAGE = "usage: handoff.py <STATE.md> <session-name> [<cwd>]"
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


def handoff(state_path: Path, session_name: str, cwd: Path) -> int:
    if not state_path.is_file():
        sys.stderr.write(f"handoff.py: STATE.md not found: {state_path}\n")
        return 1
    if sys.platform != "darwin":
        return 0
    prompt = (
        f"Read {state_path} and continue from it. "
        "Read only that file to start; it points at everything else."
    )
    input_text = f"claude --name {session_name!r} --permission-mode bypassPermissions {prompt!r}"
    result = subprocess.run(
        ["osascript", "-", str(cwd), input_text],
        input=APPLESCRIPT,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        sys.stderr.write(f"handoff.py: failed to open Ghostty tab: {result.stderr.strip()}\n")
        return 1
    sys.stdout.write(f"session: {session_name}\n")
    sys.stdout.write(f"state:   {state_path}\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) not in {2, 3}:
        sys.stderr.write(f"{USAGE}\n")
        return 64
    return handoff(Path(argv[0]), argv[1], Path(argv[2]) if len(argv) == 3 else Path.cwd())


if __name__ == "__main__":
    raise SystemExit(main())
