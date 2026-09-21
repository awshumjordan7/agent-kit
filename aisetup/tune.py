from __future__ import annotations

import json
import math
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any


class TuneError(RuntimeError):
    pass


def _confidence(samples: int) -> str:
    if samples >= 30:
        return "high"
    if samples >= 10:
        return "medium"
    return "low"


def recommendations(profile: dict[str, Any], metrics: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name, current in profile.get("agents", {}).items():
        stats = metrics.get("agents", {}).get(name)
        if not isinstance(stats, dict) or not stats.get("runs"):
            continue
        samples = int(stats["runs"])
        turns = stats.get("turns", [])
        cap = current.get("maxTurns")
        if isinstance(cap, int) and turns:
            capped = sum(turn >= cap for turn in turns)
            if capped / len(turns) >= 0.2:
                p90 = int(stats.get("p90_turns", cap))
                proposed = max(cap, math.ceil(p90 / 5) * 5)
                rows.append(
                    {
                        "knob": f"agents.{name}.maxTurns",
                        "current": cap,
                        "proposed": proposed,
                        "evidence": f"{capped}/{len(turns)} runs reached the cap; p90={p90}",
                        "confidence": _confidence(samples),
                    }
                )
        models = Counter(stats.get("models", {}))
        if models:
            proposed_model, count = models.most_common(1)[0]
            current_model = current.get("model")
            proposed = (
                current_model
                if models[current_model] / sum(models.values()) >= 0.9
                else proposed_model
            )
            rows.append(
                {
                    "knob": f"agents.{name}.model",
                    "current": current_model,
                    "proposed": proposed,
                    "evidence": f"{count}/{sum(models.values())} runs used {proposed_model}",
                    "confidence": _confidence(samples),
                }
            )
    return rows


def collect_metrics(
    repo_root: Path,
    profile: dict[str, Any],
    transcripts: Path,
    *,
    since: str | None,
    until: str | None,
    timezone_offset: str | None,
) -> dict[str, Any]:
    config = {
        "known_repos": profile.get("doctor", {}).get("known_repos", []),
        "since": since,
        "until": until,
        "timezone": timezone_offset,
    }
    command = [
        sys.executable,
        str(repo_root / "core/scripts/metrics.py"),
        "--config",
        json.dumps(config),
        "--transcripts",
        str(transcripts),
    ]
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, timeout=120, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise TuneError(f"metrics failed: {error}") from error
    if completed.returncode:
        raise TuneError(completed.stderr.strip() or "metrics failed")
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise TuneError("metrics returned invalid JSON") from error
    if not isinstance(result, dict):
        raise TuneError("metrics returned an invalid result")
    return result


def format_report(rows: list[dict[str, Any]], metrics: dict[str, Any]) -> str:
    lines = [f"peak_concurrent = {metrics.get('peak_concurrent', 0)}"]
    lines.append("knob | current | proposed | evidence | confidence")
    lines.append("--- | --- | --- | --- | ---")
    for row in rows:
        lines.append(
            f"{row['knob']} | {row['current']} | {row['proposed']} | "
            f"{row['evidence']} | {row['confidence']}"
        )
    diff = {row["knob"]: row["proposed"] for row in rows if row["current"] != row["proposed"]}
    lines.extend(("", json.dumps(diff, indent=2, sort_keys=True)))
    return "\n".join(lines) + "\n"
