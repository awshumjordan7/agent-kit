from __future__ import annotations

from pathlib import Path


def is_default_claude_home(home: Path) -> bool:
    return home.expanduser().resolve() == Path("~/.claude").expanduser().resolve()
