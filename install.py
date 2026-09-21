#!/usr/bin/env python3

from __future__ import annotations

import sys


MINIMUM_PYTHON = (3, 11)


def _check_python_version() -> None:
    if sys.version_info < MINIMUM_PYTHON:
        print(
            "agent-kit requires Python 3.11 or newer. "
            "Install it with Homebrew (`brew install python@3.12`) or your system package manager.",
            file=sys.stderr,
        )
        raise SystemExit(3)


_check_python_version()

from aisetup.cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
