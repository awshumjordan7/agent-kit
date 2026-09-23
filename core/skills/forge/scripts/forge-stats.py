#!/usr/bin/env python3
"""Report per-agent timing and token usage for a Forge run.

Usage: python3 forge-stats.py <workflow-transcript-dir> <run-dir>

Claude streaming transcripts repeat the same message with progressively fuller
content. Usage is therefore counted once per message.id, using the most complete
record, while tool calls are deduplicated by tool_use.id.
"""

from __future__ import annotations

import glob
import json
import os
import sys
from datetime import datetime
from pathlib import Path


SIGNATURES = [
    ("You orchestrate the IMPLEMENT", "implement-wrapper"),
    ("You are the Claude general reviewer", "review-claude"),
    ("You orchestrate the CODEX general review", "review-codex-wrapper"),
    ("You collect the exact Forge review inputs", "changed-files-wrapper"),
    ("You run the LOCAL GATE", "gate"),
    ("You run the SHIP stage", "ship"),
    ("You run SANDBOX QA", "sandbox-qa"),
    ("You run the acceptance-criterion SMOKE", "smoke"),
    ("You are the security lens reviewer", "lens-security"),
    ("You are the dx-audit lens reviewer", "lens-dx-audit"),
    ("You are the design-audit lens reviewer", "lens-design-audit"),
    ("You orchestrate FIX ROUND 1 (fix-gate)", "fix-gate"),
    ("You orchestrate FIX ROUND 1 (fix-1)", "fix-1"),
    ("You are FIX ROUND 2", "fix-2"),
    ("You orchestrate FIX VERIFICATION ROUND 1", "verify-1"),
    ("You orchestrate FIX VERIFICATION ROUND 2", "verify-2"),
    ("You write the Forge HANDOFF", "handoff"),
    ("You are the OPUS general reviewer", "review-claude"),
    ("You are the CLAUDE general reviewer", "review-claude"),
    ("You are the CORRECTNESS reviewer", "lens-correctness"),
    ("You are the SECURITY reviewer", "lens-security"),
    ("You are the PERFORMANCE reviewer", "lens-performance"),
    ("You are the JUDGE", "judge"),
    ("You are the Forge fix DECIDER", "decider"),
    ("Apply only this verified fix spec", "fix"),
    ("You are the FIX agent", "fix"),
    ("You orchestrate FIX VERIFICATION", "verify-wrapper"),
    ("You collect changed file paths", "changed-files-wrapper"),
    ("You run QA", "qa"),
    ("You write the HANDOFF", "handoff"),
]


def parse_ts(value: object) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def role_of(text: str) -> str | None:
    for signature, role in SIGNATURES:
        if signature in text:
            return role
    return None


def read_jsonl(path: Path):
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return
    for line in lines:
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            yield value


def load_labels(transcript_dir: Path) -> dict[str, str]:
    """Return agentId -> workflow label from journal.jsonl."""
    labels: dict[str, str] = {}
    for record in read_jsonl(transcript_dir / "journal.jsonl"):
        agent_id = record.get("agentId")
        key = record.get("key")
        if agent_id and key:
            labels.setdefault(str(agent_id), str(key))
    return labels


def content_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    return " ".join(
        str(block.get("text", "")) for block in content if isinstance(block, dict)
    )


def usage_score(usage: dict[str, object]) -> tuple[int, int]:
    """Rank progressive copies so the terminal/cumulative copy wins."""
    output = int(usage.get("output_tokens", 0) or 0)
    iterations = usage.get("iterations")
    iteration_count = len(iterations) if isinstance(iterations, list) else 0
    return output, iteration_count


def agent_stats(path: Path) -> dict[str, object]:
    first: datetime | None = None
    last: datetime | None = None
    model: str | None = None
    role: str | None = None
    usage_by_message: dict[str, dict[str, object]] = {}
    tool_ids: set[str] = set()

    for record in read_jsonl(path):
        timestamp = (
            parse_ts(record.get("timestamp")) if record.get("timestamp") else None
        )
        if timestamp:
            first = timestamp if first is None or timestamp < first else first
            last = timestamp if last is None or timestamp > last else last

        message = record.get("message")
        if not isinstance(message, dict):
            continue
        if message.get("model") and not model:
            model = str(message["model"])
        if role is None and message.get("role") == "user":
            role = role_of(content_text(message.get("content")))

        content = message.get("content")
        if isinstance(content, list):
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                tool_id = block.get("id")
                if tool_id:
                    tool_ids.add(str(tool_id))

        usage = message.get("usage")
        message_id = message.get("id")
        if not isinstance(usage, dict) or not message_id:
            continue
        key = str(message_id)
        prior = usage_by_message.get(key)
        if prior is None or usage_score(usage) >= usage_score(prior):
            usage_by_message[key] = usage

    uncached = cache_write_5m = cache_write_1h = cache_write_other = 0
    cache_read = output = 0
    for usage in usage_by_message.values():
        uncached += int(usage.get("input_tokens", 0) or 0)
        cache_read += int(usage.get("cache_read_input_tokens", 0) or 0)
        output += int(usage.get("output_tokens", 0) or 0)

        cache_creation = usage.get("cache_creation")
        if isinstance(cache_creation, dict):
            write_5m = int(cache_creation.get("ephemeral_5m_input_tokens", 0) or 0)
            write_1h = int(cache_creation.get("ephemeral_1h_input_tokens", 0) or 0)
        else:
            write_5m = write_1h = 0
        cache_write_5m += write_5m
        cache_write_1h += write_1h
        write_total = int(usage.get("cache_creation_input_tokens", 0) or 0)
        cache_write_other += max(0, write_total - write_5m - write_1h)

    wall = (last - first).total_seconds() if first and last else 0
    return {
        "model": model or "?",
        "wall": wall,
        "uncached": uncached,
        "cache_write_5m": cache_write_5m,
        "cache_write_1h": cache_write_1h,
        "cache_write_other": cache_write_other,
        "cache_read": cache_read,
        "output": output,
        "calls": len(usage_by_message),
        "tools": len(tool_ids),
        "role": role,
    }


def fmt_secs(seconds: float) -> str:
    minutes, seconds = divmod(int(seconds), 60)
    return f"{minutes}m{seconds:02d}s" if minutes else f"{seconds}s"


def codex_runs(run_dir: Path) -> list[dict[str, object]]:
    """Read current Codex CLI JSONL event streams; legacy *.log files are ignored."""
    runs: list[dict[str, object]] = []
    for path in sorted(run_dir.glob("*.jsonl")):
        started = completed = False
        input_tokens = cached_tokens = output_tokens = 0
        saw_codex_event = False
        for event in read_jsonl(path):
            event_type = event.get("type")
            if event_type in {
                "thread.started",
                "turn.started",
                "turn.completed",
                "item.started",
                "item.completed",
            }:
                saw_codex_event = True
            if event_type == "thread.started":
                started = True
            if event_type != "turn.completed":
                continue
            completed = True
            usage = event.get("usage")
            if isinstance(usage, dict):
                input_tokens += int(usage.get("input_tokens", 0) or 0)
                cached_tokens += int(usage.get("cached_input_tokens", 0) or 0)
                output_tokens += int(usage.get("output_tokens", 0) or 0)
        if saw_codex_event:
            runs.append(
                {
                    "name": path.name,
                    "started": started,
                    "completed": completed,
                    "input": input_tokens,
                    "cached": cached_tokens,
                    "output": output_tokens,
                }
            )
    return runs


def main() -> None:
    if len(sys.argv) < 3:
        print("usage: forge-stats.py <transcript-dir> <run-dir>", file=sys.stderr)
        sys.exit(2)

    transcript_dir = Path(sys.argv[1])
    run_dir = Path(sys.argv[2])
    labels = load_labels(transcript_dir)
    rows: list[dict[str, object]] = []
    for path_value in glob.glob(os.path.join(transcript_dir, "agent-*.jsonl")):
        path = Path(path_value)
        agent_id = path.name[len("agent-") : -len(".jsonl")]
        stats = agent_stats(path)
        stats["label"] = stats.get("role") or labels.get(agent_id) or agent_id[:10]
        rows.append(stats)
    rows.sort(key=lambda row: float(row["wall"]), reverse=True)
    codex = codex_runs(run_dir)

    lines = ["# Agent Stats", ""]
    lines.append(
        f"_{len(rows)} workflow agents. Agents run in parallel, so wall-times overlap; "
        "the column sum is not wall-clock time. Claude usage is deduplicated by message ID._"
    )
    lines.extend(
        [
            "",
            "| Agent | Model | Wall | Uncached in | Cache write 5m | Cache write 1h | Other cache write | Cache read | Out | Calls | Tools |",
            "|-------|-------|-----:|------------:|---------------:|---------------:|------------------:|-----------:|----:|------:|------:|",
        ]
    )
    totals = {
        "uncached": 0,
        "cache_write_5m": 0,
        "cache_write_1h": 0,
        "cache_write_other": 0,
        "cache_read": 0,
        "output": 0,
        "calls": 0,
        "tools": 0,
    }
    for row in rows:
        for key in totals:
            totals[key] += int(row[key])
        lines.append(
            f"| {row['label']} | {row['model']} | {fmt_secs(float(row['wall']))} | "
            f"{int(row['uncached']):,} | {int(row['cache_write_5m']):,} | "
            f"{int(row['cache_write_1h']):,} | {int(row['cache_write_other']):,} | "
            f"{int(row['cache_read']):,} | {int(row['output']):,} | "
            f"{int(row['calls'])} | {int(row['tools'])} |"
        )
    lines.append(
        "| **total** |  |  | "
        f"**{totals['uncached']:,}** | **{totals['cache_write_5m']:,}** | "
        f"**{totals['cache_write_1h']:,}** | **{totals['cache_write_other']:,}** | "
        f"**{totals['cache_read']:,}** | **{totals['output']:,}** | "
        f"**{totals['calls']:,}** | **{totals['tools']:,}** |"
    )
    lines.append("")

    if codex:
        lines.extend(
            [
                "## Codex runs",
                "",
                "| Event stream | Status | Input | Cached input | Output |",
                "|--------------|--------|------:|-------------:|-------:|",
            ]
        )
        for run in codex:
            if run["completed"]:
                status = "completed"
            elif run["started"]:
                status = "STARTED, NO COMPLETION (cut off / hung)"
            else:
                status = "events present, thread not started"
            lines.append(
                f"| {run['name']} | {status} | {int(run['input']):,} | "
                f"{int(run['cached']):,} | {int(run['output']):,} |"
            )
        lines.append("")

    markdown = "\n".join(lines) + "\n"
    output_path = run_dir / "agent-stats.md"
    try:
        output_path.write_text(markdown, encoding="utf-8")
    except OSError as exc:
        print(f"failed to write {output_path}: {exc}", file=sys.stderr)
        sys.exit(1)
    print(f"wrote {output_path}\n")
    print(markdown)


if __name__ == "__main__":
    main()
