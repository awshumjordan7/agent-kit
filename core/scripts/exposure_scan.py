"""Log where secret-shaped values appeared in Claude Code transcripts, never the values.

Runs under /usr/bin/python3 (3.9 on macOS) from launchd, so it uses the standard library only.
"""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_ROOT = "~/.claude/projects"
DEFAULT_OUT = "~/.claude/feedback/exposures.jsonl"
INSTALLED_SCRIPT = "~/.claude/scripts/exposure_scan.py"
SCHEDULE_LABEL = "com.agent-kit.exposure-scan"
SCHEDULE_PLIST = f"~/Library/LaunchAgents/{SCHEDULE_LABEL}.plist"
SCHEDULE_LOG = "~/.claude/feedback/exposure-scan.log"

# Expressions copied verbatim from gitleaks config/gitleaks.toml at commit
# b58d3f102cf3a2c84cb7f923d05c25c9b1aed84b. Each detector lists the gitleaks rule ids it combines.
GITLEAKS_RULES: dict[str, list[str]] = {
    # aws-access-token
    "aws-access-key-id": [r"""\b((?:A3T[A-Z0-9]|AKIA|ASIA|ABIA|ACCA)[A-Z2-7]{16})\b"""],
    # github-pat, github-oauth, github-app-token, github-refresh-token
    "github-token": [
        r"""ghp_[0-9a-zA-Z]{36}""",
        r"""gho_[0-9a-zA-Z]{36}""",
        r"""(?:ghu|ghs)_[0-9a-zA-Z]{36}""",
        r"""ghr_[0-9a-zA-Z]{36}""",
    ],
    # github-fine-grained-pat
    "github-fine-pat": [r"""github_pat_\w{82}"""],
    # slack-bot-token, slack-user-token, slack-app-token, slack-config-access-token,
    # slack-config-refresh-token, slack-legacy-bot-token, slack-legacy-token, slack-legacy-workspace-token
    "slack-token": [
        r"""xoxb-[0-9]{10,13}-[0-9]{10,13}[a-zA-Z0-9-]*""",
        r"""xox[pe](?:-[0-9]{10,13}){3}-[a-zA-Z0-9-]{28,34}""",
        r"""(?i)xapp-\d-[A-Z0-9]+-\d+-[a-z0-9]+""",
        r"""(?i)xoxe.xox[bp]-\d-[A-Z0-9]{163,166}""",
        r"""(?i)xoxe-\d-[A-Z0-9]{146}""",
        r"""xoxb-[0-9]{8,14}-[a-zA-Z0-9]{18,26}""",
        r"""xox[os]-\d+-\d+-\d+-[a-fA-F\d]+""",
        r"""xox[ar]-(?:\d-)?[0-9a-zA-Z]{8,48}""",
    ],
    # slack-webhook-url
    "slack-webhook": [r"""(?:https?://)?hooks.slack.com/(?:services|workflows|triggers)/[A-Za-z0-9+/]{43,56}"""],
    # gcp-api-key
    "google-api-key": [r"""\b(AIza[\w-]{35})(?:[\x60'"\s;]|\\[nr]|$)"""],
    # stripe-access-token
    "stripe-key": [r"""\b((?:sk|rk)_(?:test|live|prod)_[a-zA-Z0-9]{10,99})(?:[\x60'"\s;]|\\[nr]|$)"""],
    # openai-api-key
    "openai-key": [
        r"""\b(sk-(?:proj|svcacct|admin)-(?:[A-Za-z0-9_-]{74}|[A-Za-z0-9_-]{58})T3BlbkFJ(?:[A-Za-z0-9_-]{74}|[A-Za-z0-9_-]{58})\b|sk-[a-zA-Z0-9]{20}T3BlbkFJ[a-zA-Z0-9]{20})(?:[\x60'"\s;]|\\[nr]|$)"""
    ],
    # anthropic-api-key, anthropic-admin-api-key
    "anthropic-key": [
        r"""\b(sk-ant-api03-[a-zA-Z0-9_\-]{93}AA)(?:[\x60'"\s;]|\\[nr]|$)""",
        r"""\b(sk-ant-admin01-[a-zA-Z0-9_\-]{93}AA)(?:[\x60'"\s;]|\\[nr]|$)""",
    ],
    # jwt
    "jwt": [r"""\b(ey[a-zA-Z0-9]{17,}\.ey[a-zA-Z0-9\/\\_-]{17,}\.(?:[a-zA-Z0-9\/\\_-]{10,}={0,2})?)(?:[\x60'"\s;]|\\[nr]|$)"""],
    # private-key
    "pem-private-key": [r"""(?i)-----BEGIN[ A-Z0-9_-]{0,100}PRIVATE KEY(?: BLOCK)?-----[\s\S-]{64,}?KEY(?: BLOCK)?-----"""],
}

# gitleaks has no AWS secret-key rule, so this one is local.
CUSTOM_RULES: dict[str, list[str]] = {
    "aws-secret-assign": [r"""AWS_SECRET_ACCESS_KEY["']?\s*[=:]\s*["']?[A-Za-z0-9/+=]{40}(?![A-Za-z0-9/+=])"""],
}

DETECTORS: dict[str, list[re.Pattern[str]]] = {
    name: [re.compile(expression, re.ASCII) for expression in expressions]
    for name, expressions in {**GITLEAKS_RULES, **CUSTOM_RULES}.items()
}
# gitleaks allowlist for aws-access-token: AWS documentation keys end in EXAMPLE.
AWS_EXAMPLE = re.compile(r".+EXAMPLE$")

# Line-anchored, so it runs on text with the Read tool's line-number prefix removed.
ENV_ASSIGN = re.compile(
    r"""^[ \t]*(?:export[ \t]+)?(?:[A-Z][A-Z0-9_]*)?(?:SECRET|TOKEN|PASSWORD|PASSWD|API_KEY|PRIVATE_KEY|ACCESS_KEY|_KEY)[ \t]*=[ \t]*["']?([A-Za-z0-9+/_.=-]{16,})""",
    re.MULTILINE,
)
ENV_PLACEHOLDER = re.compile(
    r"(?i)^(?:your|xxx|changeme|example|placeholder|dummy|test|fake|redacted|replace|none|null|true|false)"
    r"|(?:^|[_-])(?:here|example|placeholder)$"
)
READ_LINE_NUMBER = re.compile(r"^\s*\d+\t", re.MULTILINE)


def _record_texts(record: dict, tool_names: dict[str, str]) -> list[tuple[str, str]]:
    """Return (tool name, text) for each tool_result block, from message.content only."""
    message = record.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, list):
        return []
    texts = []
    for block in content:
        if not isinstance(block, dict) or block.get("type") != "tool_result":
            continue
        tool = tool_names.get(block.get("tool_use_id", ""), "unknown")
        result = block.get("content")
        if isinstance(result, str):
            texts.append((tool, result))
        elif isinstance(result, list):
            for part in result:
                if isinstance(part, dict) and part.get("type") == "text" and isinstance(part.get("text"), str):
                    texts.append((tool, part["text"]))
    return texts


def _patterns_in(text: str) -> set[str]:
    found = set()
    for name, expressions in DETECTORS.items():
        for expression in expressions:
            for match in expression.finditer(text):
                if name == "aws-access-key-id" and AWS_EXAMPLE.match(match.group(0)):
                    continue
                found.add(name)
                break
            if name in found:
                break
    for match in ENV_ASSIGN.finditer(READ_LINE_NUMBER.sub("", text)):
        if not ENV_PLACEHOLDER.search(match.group(1)):
            found.add("env-secret-assign")
            break
    return found


def _is_forge_session(session_file: Path, cache: dict[Path, bool]) -> bool:
    if session_file not in cache:
        try:
            with session_file.open(encoding="utf-8", errors="replace") as handle:
                cache[session_file] = any('"skill":"forge"' in line for line in handle)
        except OSError:
            cache[session_file] = False
    return cache[session_file]


def _kind(path: Path, forge_cache: dict[Path, bool]) -> str:
    if path.parent.name == "subagents":
        session_file = path.parent.parent.with_suffix(".jsonl")
        return "forge" if _is_forge_session(session_file, forge_cache) else "subagent"
    return "forge" if _is_forge_session(path, forge_cache) else "main"


def _scan_file(path: Path, root: Path, cutoff_iso: str, kind: str) -> list[dict]:
    rows = []
    tool_names: dict[str, str] = {}
    session = str(path.relative_to(root))
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line_number, line in enumerate(handle, 1):
            if '"tool_use"' not in line and '"tool_result"' not in line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(record, dict):
                continue
            message = record.get("message")
            if record.get("type") == "assistant" and isinstance(message, dict) and isinstance(message.get("content"), list):
                for block in message["content"]:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        tool_names[block.get("id", "")] = block.get("name", "unknown")
                continue
            if record.get("type") != "user":
                continue
            timestamp = record.get("timestamp")
            if not isinstance(timestamp, str) or timestamp < cutoff_iso:
                continue
            seen = set()
            for tool, text in _record_texts(record, tool_names):
                for pattern in sorted(_patterns_in(text)):
                    if (pattern, tool) in seen:
                        continue
                    seen.add((pattern, tool))
                    rows.append(
                        {"ts": timestamp, "pattern": pattern, "session": session, "line": line_number, "tool": tool, "kind": kind}
                    )
    return rows


def scan(root: Path, days: int) -> tuple[int, list[dict]]:
    cutoff = time.time() - days * 86400
    cutoff_iso = datetime.fromtimestamp(cutoff, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    forge_cache: dict[Path, bool] = {}
    files = 0
    rows: list[dict] = []
    for path in sorted(root.rglob("*.jsonl")):
        try:
            if path.stat().st_mtime < cutoff:
                continue
            rows.extend(_scan_file(path, root, cutoff_iso, _kind(path, forge_cache)))
        except OSError as error:
            sys.stderr.write(f"skipped {path}: {error}\n")
            continue
        files += 1
    return files, rows


def schedule_plist() -> dict:
    log = str(Path(SCHEDULE_LOG).expanduser())
    return {
        "Label": SCHEDULE_LABEL,
        "ProgramArguments": ["/usr/bin/python3", str(Path(INSTALLED_SCRIPT).expanduser()), "--days", "7"],
        # Missing calendar keys are wildcards, so Minute 0 keeps this to one run a week.
        "StartCalendarInterval": {"Weekday": 1, "Hour": 9, "Minute": 0},
        "StandardOutPath": log,
        "StandardErrorPath": log,
    }


def install_schedule(dry_run: bool) -> int:
    content = plistlib.dumps(schedule_plist()).decode("utf-8")
    if dry_run:
        sys.stdout.write(content)
        return 0
    plist_path = Path(SCHEDULE_PLIST).expanduser()
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    Path(SCHEDULE_LOG).expanduser().parent.mkdir(parents=True, exist_ok=True)
    plist_path.write_text(content, encoding="utf-8")
    domain = f"gui/{os.getuid()}"
    loaded = subprocess.run(
        ["launchctl", "print", f"{domain}/{SCHEDULE_LABEL}"], capture_output=True, check=False
    )
    try:
        if loaded.returncode == 0:
            subprocess.run(["launchctl", "bootout", f"{domain}/{SCHEDULE_LABEL}"], capture_output=True, text=True, check=True)
        subprocess.run(["launchctl", "bootstrap", domain, str(plist_path)], capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as error:
        sys.stderr.write(f"launchctl {error.cmd[1]} failed ({error.returncode}): {error.stderr.strip()}\n")
        return 1
    sys.stdout.write(f"installed {plist_path} ({domain}/{SCHEDULE_LABEL})\n")
    return 0


def _positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be 1 or more")
    return number


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="exposure_scan.py", description=__doc__)
    parser.add_argument("--days", type=_positive_int, default=7, help="scan transcripts modified in the last N days")
    parser.add_argument("--root", default=DEFAULT_ROOT, help=f"transcript folder (default {DEFAULT_ROOT})")
    parser.add_argument("--out", help=f"log file to append rows to (default {DEFAULT_OUT})")
    parser.add_argument("--install-schedule", action="store_true", help="install the weekly launchd job")
    parser.add_argument("--dry-run", action="store_true", help="with --install-schedule, print the plist only")
    args = parser.parse_args(argv)

    if args.dry_run and not args.install_schedule:
        parser.error("--dry-run needs --install-schedule")
    if args.install_schedule:
        return install_schedule(args.dry_run)

    root = Path(args.root).expanduser()
    if not root.is_dir():
        sys.stderr.write(f"root folder not found: {root}\n")
        return 2
    if args.out is None:
        out = Path(DEFAULT_OUT).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
    else:
        out = Path(args.out).expanduser()
        if not out.parent.is_dir():
            sys.stderr.write(f"output folder not found: {out.parent}\n")
            return 2

    files, rows = scan(root, args.days)
    with out.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")
    sys.stdout.write(f"scanned {files} transcripts from the last {args.days} days; appended {len(rows)} rows to {out}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
