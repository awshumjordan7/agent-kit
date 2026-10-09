#!/usr/bin/env python3
"""Fail when a diff changes an instruction file without adding a CHANGELOG.md line.

Usage: check_changelog.py --base <sha> --head <sha>

Compares `base...head` (changes on head since the merge base). Exit 1 lists the
instruction files when CHANGELOG.md gains no `- ` line; exit 2 when git fails; exit 0 otherwise.
Standard library only. ship-pr's verifier step uses the same instruction-file patterns.
"""

import argparse
import re
import subprocess
import sys

INSTRUCTION_PATTERNS = (
    re.compile(r"(^|/)CLAUDE(\.fragment)?\.md$"),
    re.compile(r"(^|/)AGENTS\.md$"),
    re.compile(r"(^|/)agents/[^/]+\.md$"),
    re.compile(r"(^|/)skills/.+\.md$"),
    re.compile(r"(^|/)references/[^/]+\.md$"),
)
CHANGELOG = "CHANGELOG.md"


def git(*args: str) -> str:
    result = subprocess.run(["git", *args], capture_output=True, text=True, check=True)
    return result.stdout


def instruction_files(base: str, head: str) -> list[str]:
    names = git("diff", "--name-only", f"{base}...{head}").splitlines()
    return sorted(name for name in names if any(p.search(name) for p in INSTRUCTION_PATTERNS))


def changelog_lines_added(base: str, head: str) -> list[str]:
    diff = git("diff", "--unified=0", f"{base}...{head}", "--", CHANGELOG)
    return [line[1:] for line in diff.splitlines() if line.startswith("+- ")]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    args = parser.parse_args()

    try:
        changed = instruction_files(args.base, args.head)
        added = changelog_lines_added(args.base, args.head) if changed else []
    except subprocess.CalledProcessError as exc:
        print(f"git {' '.join(exc.cmd[1:])} failed: {exc.stderr.strip()}", file=sys.stderr)
        return 2

    if changed and not added:
        print(f"Instruction files changed without a {CHANGELOG} line:", file=sys.stderr)
        for name in changed:
            print(f"  {name}", file=sys.stderr)
        print(
            f"Add `- <paths or area>: <reason>` under today's `## YYYY-MM-DD` heading",
            f"in {CHANGELOG}.",
            file=sys.stderr,
        )
        return 1

    if changed:
        print(f"{len(changed)} instruction file(s) changed; {len(added)} changelog line(s) added.")
    else:
        print("No instruction files changed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
