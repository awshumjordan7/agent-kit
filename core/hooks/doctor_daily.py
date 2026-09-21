from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=False, capture_output=True, text=True, timeout=20)


def run_daily(layers_root: Path, claude_home: Path, today: date | None = None) -> str:
    today = today or date.today()
    stamp = layers_root / "doctor-daily.stamp"
    if stamp.is_file() and stamp.read_text(encoding="utf-8").strip() == today.isoformat():
        return ""
    layers_root.mkdir(parents=True, exist_ok=True)
    stamp.write_text(today.isoformat() + "\n", encoding="utf-8")
    profile_path = layers_root / "profile.json"
    if not profile_path.is_file():
        return ""
    try:
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
        repo = Path(profile["layers"]["core"]["path"])
        install = repo / "install.py"
        doctor = _run(
            [sys.executable, str(install), "doctor", "--quiet", "--home", str(claude_home)]
        )
        check = _run(
            [
                sys.executable,
                str(install),
                "update",
                "--check",
                "--home",
                str(claude_home),
                "--layers-root",
                str(layers_root),
            ]
        )
    except (OSError, KeyError, json.JSONDecodeError, subprocess.TimeoutExpired):
        return ""
    messages = [doctor.stdout.strip(), doctor.stderr.strip()]
    statuses = []
    if check.returncode == 0:
        for line in check.stdout.splitlines():
            try:
                status = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(status, dict):
                continue
            statuses.append(status)
            if status.get("repo") == "agent-kit" and status.get("behind", 0) > 0:
                messages.append(
                    f"agent-kit: {status['behind']} new commits since your install. "
                    f"Run: python3 {repo}/install.py update"
                )
        if profile.get("auto_update") and any(status.get("behind", 0) > 0 for status in statuses):
            try:
                _run(
                    [
                        sys.executable,
                        str(install),
                        "update",
                        "--home",
                        str(claude_home),
                        "--layers-root",
                        str(layers_root),
                    ]
                )
            except (OSError, subprocess.TimeoutExpired):
                pass
    return "\n".join(message for message in messages if message)


def main() -> int:
    layers_root = Path(os.environ.get("AISETUP_LAYERS_ROOT", "~/.ai-setup")).expanduser()
    claude_home = Path(os.environ.get("CLAUDE_HOME", "~/.claude")).expanduser()
    output = run_daily(layers_root, claude_home)
    if output:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
