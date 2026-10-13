#!/usr/bin/env python3
"""PreToolUse guard: block Bash commands and Artifact uploads that name an env file.

Env files are `.env`, `.env.<suffix>` other than `.env.example`, `.envrc`, `.env_<suffix>`,
and any path with a `.envs/` folder. The deny rules in settings.json cover the Read, Grep,
Edit, Write and NotebookEdit tools and every other credential file, so this hook does not.

Fail-open: malformed JSON or an unexpected payload shape exits 0. This is an accident
guard, not a security boundary. A command that reaches an env file without naming it
(a variable, a glob such as `.e*`, an interpreter that builds the path) is not seen.
"""

from __future__ import annotations

import json
import posixpath
import re
import sys

ENV_FILE = re.compile(r"\.env|\.envrc|\.env\.(?!example$).+|\.env_.+|\.env[*?\[].*", re.IGNORECASE)
# Shell quoting, operators and separators end a word. `=`, `:` and `@` split forms such as
# `--env-file=.env`, `git show HEAD:.env` and `curl -d @.env`.
WORD_BREAK = re.compile(r"""[\s'"`;|&<>(){}=,:@]+""")

BASH_ROUTES = (
    "To run a command with an env file loaded, follow ~/.claude/references/env-recipe.md: "
    "write `<runDir>/with-env.sh` with the Write tool, then run "
    "`bash <runDir>/with-env.sh <command>`. Repository tests can run through forge's "
    "`~/.claude/skills/forge/scripts/gate.sh`. Never source an env file inline or print its values.\n"
    "If the name is only text, such as a commit message or a .gitignore line, write that text "
    "with the Write or Edit tool and pass the file (for example `git commit -F <file>`)."
)
ARTIFACT_ROUTES = (
    "An Artifact upload puts the file on a hosted page. Publish a copy with the values removed, "
    "or list the variable names in the page text instead."
)


def env_path(path: str) -> bool:
    """Return True when the path's file name is an env file or a folder in it is `.envs`."""
    parts = path.split("/")
    return bool(ENV_FILE.fullmatch(parts[-1])) or any(p.lower() == ".envs" for p in parts[:-1])


def command_hit(command: str) -> str | None:
    """Return the first word of the command that names an env file, or None."""
    return next((word for word in WORD_BREAK.split(command) if env_path(word)), None)


def artifact_paths(tool_input: dict) -> list[str]:
    """Return the local paths an Artifact call names.

    `files` maps published paths to sources: a str, or a dict whose `from` is the source.
    A dict with `artifact` is a server-side copy and None is a removal, so neither names a
    local file. The list form of `files` names each source as an item's `path`. A non-empty
    `root` prefixes every `files` source.
    """
    paths = [tool_input.get("file_path")]
    if isinstance(file_paths := tool_input.get("file_paths"), list):
        paths += file_paths
    files, sources = tool_input.get("files"), []
    if isinstance(files, dict):
        for source in files.values():
            if isinstance(source, dict):
                source = None if "artifact" in source else source.get("from")
            sources.append(source)
    elif isinstance(files, list):
        sources = [item.get("path") if isinstance(item, dict) else item for item in files]
    root = tool_input.get("root")
    if isinstance(root, str) and root:
        sources = [posixpath.join(root, s) if isinstance(s, str) else s for s in sources]
    return [p for p in paths + sources if isinstance(p, str)]


def block(noun: str, label: str, value: str, routes: str) -> int:
    # The rule sits in parentheses on the first line so a parser can read it.
    print(
        f"Blocked by block_secret_reads hook (rule env-file): this {noun} names an env file.\n"
        f"{label}: `{' '.join(value.split())[:120]}`\n{routes}",
        file=sys.stderr,
    )
    return 2


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError, UnicodeError):
        return 0
    if not isinstance(payload, dict) or not isinstance(payload.get("tool_input"), dict):
        return 0
    tool_name, tool_input = payload.get("tool_name"), payload["tool_input"]

    if tool_name == "Bash":
        command = tool_input.get("command")
        if isinstance(command, str) and (word := command_hit(command)):
            return block("command", "Matched", word, BASH_ROUTES)
    elif tool_name == "Artifact":
        if path := next((p for p in artifact_paths(tool_input) if env_path(p)), None):
            return block("Artifact upload", "Path", path, ARTIFACT_ROUTES)
    return 0


if __name__ == "__main__":
    sys.exit(main())
