from __future__ import annotations

import argparse

from tests.golden import update_expected


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--update", action="store_true", required=True)
    parser.parse_args()
    update_expected()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
