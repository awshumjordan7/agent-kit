"""PostToolUse hook for Write and Edit: run ruff on a changed .py file and add its findings to context.

Only Python is linted. JS and TS files get no hook output; their lint runs in the forge gate.
Fail-open: any missing tool, timeout or non-file path returns no output and exit 0.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


def lint_command(path: Path) -> tuple[str, ...] | None:
    if path.suffix == ".py" and shutil.which("ruff"):
        return ("ruff", "check", str(path))
    return None


def run(payload: dict[str, Any]) -> str:
    raw_path = payload.get("tool_input", {}).get("file_path")
    if not isinstance(raw_path, str):
        return ""
    path = Path(raw_path)
    if not path.is_file():
        return ""
    command = lint_command(path)
    if command is None:
        return ""
    try:
        result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    output = (result.stdout + result.stderr).strip()
    if result.returncode == 0 or not output:
        return ""
    return f"Lint (ruff): {path}\n{output}"


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    output = run(payload)
    if output:
        message = output[:8000] + "\nFix findings on lines you changed; leave pre-existing ones unless asked."
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": message}}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
