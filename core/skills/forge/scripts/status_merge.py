from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path


def merge_status(status: dict, patch: dict) -> dict:
    merged = dict(status)
    for key, value in patch.items():
        if key == "criteria":
            criteria = [dict(item) for item in merged.get("criteria", [])]
            for index, incoming in enumerate(value):
                match = next(
                    (
                        item
                        for item in criteria
                        if item.get("text") and item.get("text") == incoming.get("text")
                    ),
                    criteria[index] if index < len(criteria) else None,
                )
                if match is None:
                    criteria.append(dict(incoming))
                else:
                    match.update(incoming)
            merged[key] = criteria
        elif key == "rounds":
            merged[key] = {**merged.get(key, {}), **value}
        else:
            merged[key] = value
    merged["updated"] = datetime.now(UTC).isoformat()
    return merged


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--status", type=Path, required=True)
    parser.add_argument("--patch-json", required=True)
    args = parser.parse_args()
    status = (
        json.loads(args.status.read_text(encoding="utf-8"))
        if args.status.is_file()
        else {"criteria": [], "rounds": {}, "open_findings": []}
    )
    merged = merge_status(status, json.loads(args.patch_json))
    args.status.parent.mkdir(parents=True, exist_ok=True)
    args.status.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
    sys.stdout.write(json.dumps({"written": True}, separators=(",", ":")) + "\n")


if __name__ == "__main__":
    main()
