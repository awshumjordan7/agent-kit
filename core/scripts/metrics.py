#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _iter_records(root: Path):
    if not root.is_dir():
        return
    for path in sorted(root.rglob("*.jsonl")):
        try:
            lines = path.open(encoding="utf-8", errors="replace")
        except OSError:
            continue
        with lines:
            for line in lines:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(record, dict):
                    yield record


def _percentile(values: list[float], percentile: int) -> float:
    if not values:
        return 0
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * percentile / 100) - 1)
    return ordered[index]


def _timezone_offset(value: Any) -> timedelta:
    if not isinstance(value, str) or len(value) != 6 or value[0] not in "+-" or value[3] != ":":
        return timedelta()
    try:
        hours, minutes = int(value[1:3]), int(value[4:6])
    except ValueError:
        return timedelta()
    direction = 1 if value[0] == "+" else -1
    return direction * timedelta(hours=hours, minutes=minutes)


def analyze(transcripts: Path, config: dict[str, Any]) -> dict[str, Any]:
    since = config.get("since")
    until = config.get("until")
    offset = _timezone_offset(config.get("timezone"))
    known_repos = set(config.get("known_repos", []))
    agents: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"turns": [], "models": Counter(), "runs": 0}
    )
    intervals: dict[str, list[tuple[datetime, datetime]]] = defaultdict(list)
    for record in _iter_records(transcripts):
        start = _timestamp(record.get("spawn_ts") or record.get("timestamp"))
        if start is None:
            continue
        if known_repos and record.get("repo") and record["repo"] not in known_repos:
            continue
        day = (start + offset).date().isoformat()
        if (since and day < since) or (until and day > until):
            continue
        agent_type = record.get("agent_type") or record.get("subagent_type")
        if not isinstance(agent_type, str):
            continue
        session = str(record.get("session_id", "unknown"))
        duration = record.get("duration_s", 0)
        if not isinstance(duration, (int, float)):
            duration = 0
        intervals[session].append((start, start + timedelta(seconds=max(0, duration))))
        stats = agents[agent_type]
        stats["runs"] += 1
        turns = record.get("turns")
        if isinstance(turns, int):
            stats["turns"].append(turns)
        model = record.get("model") or record.get("requested_model")
        if isinstance(model, str) and model:
            stats["models"][model] += 1

    peak = 0
    for session_intervals in intervals.values():
        events = []
        for start, end in session_intervals:
            events.extend(((start, 1), (end, -1)))
        active = 0
        for _, delta in sorted(events, key=lambda item: (item[0], item[1])):
            active += delta
            peak = max(peak, active)

    return {
        "peak_concurrent": peak,
        "agents": {
            name: {
                "runs": stats["runs"],
                "turns": stats["turns"],
                "p90_turns": _percentile(stats["turns"], 90),
                "models": dict(stats["models"]),
            }
            for name, stats in sorted(agents.items())
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize local agent transcripts")
    parser.add_argument("--config", required=True, help="JSON metrics configuration")
    parser.add_argument("--transcripts", required=True, type=Path)
    args = parser.parse_args()
    try:
        config = json.loads(args.config)
    except json.JSONDecodeError as error:
        parser.error(f"invalid --config JSON: {error}")
    sys.stdout.write(json.dumps(analyze(args.transcripts, config), sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
