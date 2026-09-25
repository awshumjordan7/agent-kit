from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

TOKEN_PATTERNS = (
    re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9]{8,}"),
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"xox[baprs]-"),
    re.compile(r"/hook/[0-9a-f]{8}"),
)
SKIP_DIRECTORIES = {".git", ".pytest_cache", ".venv", "__pycache__", "node_modules"}


@dataclass(frozen=True)
class DenylistHit:
    path: Path
    line: int
    entry: str


def load_entries(path: Path) -> tuple[str, ...]:
    entries: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        entry = line.strip()
        if entry and not entry.startswith("#"):
            entries.append(entry)
    return tuple(entries)


def scan_tree(root: Path, entries: tuple[str, ...] = ()) -> list[DenylistHit]:
    hits: list[DenylistHit] = []
    lowered = tuple((entry, entry.casefold()) for entry in entries)
    for path in sorted(root.rglob("*")):
        if not path.is_file() or any(part in SKIP_DIRECTORIES for part in path.parts):
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        relative = path.relative_to(root)
        for number, line in enumerate(lines, start=1):
            folded = line.casefold()
            for entry, folded_entry in lowered:
                if folded_entry in folded:
                    hits.append(DenylistHit(relative, number, entry))
            for pattern in TOKEN_PATTERNS:
                match = pattern.search(line)
                if match:
                    hits.append(DenylistHit(relative, number, match.group(0)))
    return hits
