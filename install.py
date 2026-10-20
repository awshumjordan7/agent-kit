#!/usr/bin/env python3

from __future__ import annotations

import os
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


def _check_platform() -> None:
    if sys.platform == "win32":
        print(
            "agent-kit runs inside WSL2 (Ubuntu 24.04), not in native Windows or PowerShell. "
            'See README.md, "Windows 10 and 11 (WSL2)".',
            file=sys.stderr,
        )
        raise SystemExit(3)


def _check_sandbox() -> None:
    # Claude Code sets SANDBOX_RUNTIME only in sandboxed Bash calls; any value counts.
    if "SANDBOX_RUNTIME" in os.environ:
        print(
            "install.py must run outside the Bash sandbox, and this call ran inside it. "
            "Run it again as one bare Bash call spelled exactly python3 <agent-kit checkout>/install.py <args>: "
            "no cd prefix, pipe, redirect, 2>&1, ';' or '&&', with the checkout path as written.",
            file=sys.stderr,
        )
        raise SystemExit(86)


_check_platform()
_check_sandbox()
_check_python_version()

from aisetup.cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
