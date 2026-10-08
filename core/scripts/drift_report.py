from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

METRICS_NAME = "drift-metrics.jsonl"
REVIEW_DONE_NAME = "drift-review-done"


def _drift_state_dir() -> Path:
    return Path(os.environ.get("DRIFT_STATE_DIR") or "~/.claude/state").expanduser()


def _read_metrics(path: Path) -> list[dict]:
    records = []
    with path.open(encoding="utf-8", errors="replace") as handle:
        for number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except ValueError:
                sys.stderr.write(f"drift_report.py: skipping unreadable line {number}\n")
                continue
            if isinstance(item, dict):
                records.append(item)
    return records


def _unreflected_rate(records: list[dict]) -> str:
    counted = [
        item["unreflected"]
        for item in records
        if item.get("outcome") == "launched" and isinstance(item.get("unreflected"), int)
    ]
    if not counted:
        return "n/a"
    return f"{sum(counted) / len(counted):.2f} ({sum(counted)} over {len(counted)} launched)"


def _print_block(title: str, records: list[dict]) -> None:
    outcomes = Counter(str(item.get("outcome")) for item in records)
    sys.stdout.write(f"{title}\n")
    for outcome, count in sorted(outcomes.items()):
        sys.stdout.write(f"  {outcome}: {count}\n")
    sys.stdout.write(f"  unreflected per launched handoff: {_unreflected_rate(records)}\n")


def report(path: Path) -> int:
    try:
        records = _read_metrics(path)
    except FileNotFoundError:
        sys.stderr.write(f"drift_report.py: no metrics yet at {path}\n")
        return 1
    except OSError as error:
        sys.stderr.write(f"drift_report.py: failed to read {path}: {error}\n")
        return 1
    by_run: dict[str, list[dict]] = defaultdict(list)
    for item in records:
        by_run[str(item.get("run_dir") or "(no run dir)")].append(item)
    for run_dir in sorted(by_run):
        _print_block(run_dir, by_run[run_dir])
    _print_block(f"total ({len(records)} handoff attempts)", records)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Summarise handoff drift metrics.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--mark-reviewed",
        action="store_true",
        help="record that the review is done; handoff.py stops printing the reminder",
    )
    group.add_argument(
        "--reset-review",
        action="store_true",
        help="delete the review record to start a new review cycle",
    )
    parser.add_argument("--file", type=Path, help="metrics file (default: the global one)")
    args = parser.parse_args(argv)
    state_dir = _drift_state_dir()
    done = state_dir / REVIEW_DONE_NAME
    if args.mark_reviewed:
        try:
            state_dir.mkdir(parents=True, exist_ok=True)
            done.write_text(f"{date.today().isoformat()}\n", encoding="utf-8")
        except OSError as error:
            sys.stderr.write(f"drift_report.py: failed to write {done}: {error}\n")
            return 1
        sys.stdout.write(f"review marked done: {done}\n")
        return 0
    if args.reset_review:
        try:
            done.unlink(missing_ok=True)
        except OSError as error:
            sys.stderr.write(f"drift_report.py: failed to delete {done}: {error}\n")
            return 1
        sys.stdout.write("review cycle reset\n")
        return 0
    return report(args.file or state_dir / METRICS_NAME)


if __name__ == "__main__":
    raise SystemExit(main())
