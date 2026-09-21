from __future__ import annotations

import argparse
import sys
from pathlib import Path


def invalid_paths(root: Path, paths: list[Path]) -> list[Path]:
    root = root.resolve()
    invalid: list[Path] = []
    for path in paths:
        resolved = path.resolve()
        try:
            resolved.relative_to(root)
        except ValueError:
            invalid.append(path)
            continue
        if not resolved.exists():
            invalid.append(path)
    return invalid


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate content-pipeline input paths")
    parser.add_argument("root", type=Path)
    parser.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args()
    invalid = invalid_paths(args.root, args.paths)
    for path in invalid:
        sys.stdout.write(f"{path}\n")
    return 1 if invalid else 0


if __name__ == "__main__":
    raise SystemExit(main())
