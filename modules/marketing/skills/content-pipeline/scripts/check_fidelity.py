from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

URL = re.compile(r"https?://[^\s)>\]]+")
FENCE = re.compile(r"```[^\n]*\n.*?```", re.DOTALL)


def missing_evidence(source: str, draft: str) -> list[str]:
    required = set(URL.findall(source)) | {block.strip() for block in FENCE.findall(source)}
    return sorted(item for item in required if item not in draft)


def main() -> int:
    parser = argparse.ArgumentParser(description="Check that a draft retains source links and code")
    parser.add_argument("source", type=Path)
    parser.add_argument("draft", type=Path)
    args = parser.parse_args()
    missing = missing_evidence(
        args.source.read_text(encoding="utf-8"),
        args.draft.read_text(encoding="utf-8"),
    )
    for item in missing:
        sys.stdout.write(f"missing: {item}\n")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
