from __future__ import annotations

import shutil
import sys

CORE_DEPENDENCIES = ("python3", "claude", "git", "bash", "jq")

INSTALL_HINTS = {
    "claude": "Install Claude Code and sign in: https://docs.anthropic.com/en/docs/claude-code",
    "git": "Install Git with Xcode Command Line Tools or your system package manager.",
    "bash": "Install Bash with your system package manager.",
    "jq": "Install jq with `brew install jq` or your system package manager.",
    "node": "Install Node.js from https://nodejs.org or your system package manager.",
    "codex": "Install the Codex CLI before enabling the codex module.",
    "gh": "Install GitHub CLI from https://cli.github.com.",
}


class MissingDependencyError(RuntimeError):
    def __init__(self, names: list[str]) -> None:
        self.names = names
        super().__init__(f"missing dependencies: {', '.join(names)}")


def missing_dependencies(names: list[str] | tuple[str, ...]) -> list[str]:
    missing: list[str] = []
    for name in names:
        if name == "python3":
            if sys.version_info < (3, 11):
                missing.append(name)
        elif shutil.which(name) is None:
            missing.append(name)
    return missing


def check_dependencies(names: list[str] | tuple[str, ...]) -> None:
    missing = missing_dependencies(names)
    if missing:
        raise MissingDependencyError(missing)


def format_missing_dependencies(error: MissingDependencyError) -> str:
    lines = [str(error)]
    lines.extend(INSTALL_HINTS.get(name, f"Install {name} and try again.") for name in error.names)
    return "\n".join(lines)
