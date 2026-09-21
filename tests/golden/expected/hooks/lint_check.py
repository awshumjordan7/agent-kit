from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


def _project_root(path: Path) -> Path | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(path.parent), "rev-parse", "--show-toplevel"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return Path(result.stdout.strip()) if result.returncode == 0 else None


def lint_command(path: Path) -> tuple[str, ...] | None:
    if path.suffix == ".py" and shutil.which("ruff"):
        return ("ruff", "check", str(path))
    if path.suffix not in {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}:
        return None
    root = _project_root(path)
    local_eslint = root / "node_modules/.bin/eslint" if root else None
    if local_eslint and local_eslint.is_file():
        return (str(local_eslint), str(path))
    if shutil.which("eslint"):
        return ("eslint", str(path))
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
    if not output:
        return ""
    tool = "ruff" if path.suffix == ".py" else "eslint"
    return f"Lint ({tool}): {path}\n{output}"


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    output = run(payload)
    if output:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
