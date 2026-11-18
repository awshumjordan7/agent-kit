from __future__ import annotations

import os
import shutil
import sys

CORE_DEPENDENCIES = ("python3", "claude", "git", "bash", "jq")

# Only forge and ship-pr scripts call jq, and forge does not run on native Windows yet.
WINDOWS_WARN_ONLY = ("jq",)
JQ_SCRIPTS = (
    "core/skills/forge/scripts/codex-exec.sh",
    "core/skills/forge/scripts/build-code-review-prompt.sh",
    "core/skills/ship-pr/scripts/resolve-base-branch.sh",
)

INSTALL_HINTS = {
    "claude": "Install Claude Code and sign in: https://docs.anthropic.com/en/docs/claude-code",
    "git": "Install Git with Xcode Command Line Tools or your system package manager.",
    "bash": (
        "Install Git for Windows (it brings Git Bash), or set CLAUDE_CODE_GIT_BASH_PATH to bash.exe."
        if sys.platform == "win32"
        else "Install Bash with your system package manager."
    ),
    "jq": "Install jq with `brew install jq` or your system package manager.",
    "node": "Install Node.js from https://nodejs.org or your system package manager.",
    "codex": "Install the Codex CLI before enabling the codex module.",
    "gh": "Install GitHub CLI from https://cli.github.com.",
}


class MissingDependencyError(RuntimeError):
    def __init__(self, names: list[str]) -> None:
        self.names = names
        super().__init__(f"missing dependencies: {', '.join(names)}")


# Claude Code on Windows runs hooks with Git Bash. The bash.exe in System32 is the WSL
# launcher, which cannot run them.
def git_bash() -> str | None:
    configured = os.environ.get("CLAUDE_CODE_GIT_BASH_PATH")
    if configured and os.path.isfile(configured):
        return configured
    found = shutil.which("bash")
    if found:
        system32 = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")
        if not os.path.normcase(os.path.abspath(found)).startswith(
            os.path.normcase(system32) + os.sep
        ):
            return found
    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    default = os.path.join(program_files, "Git", "bin", "bash.exe")
    return default if os.path.isfile(default) else None


def missing_dependencies(names: list[str] | tuple[str, ...]) -> list[str]:
    missing: list[str] = []
    for name in names:
        if name == "python3":
            if sys.version_info < (3, 11):
                missing.append(name)
        elif name == "bash" and sys.platform == "win32":
            if git_bash() is None:
                missing.append(name)
        elif shutil.which(name) is None:
            missing.append(name)
    return missing


def check_dependencies(names: list[str] | tuple[str, ...]) -> None:
    if sys.platform == "win32":
        names = [name for name in names if name not in WINDOWS_WARN_ONLY]
    missing = missing_dependencies(names)
    if missing:
        raise MissingDependencyError(missing)


def format_missing_dependencies(error: MissingDependencyError) -> str:
    lines = [str(error)]
    lines.extend(INSTALL_HINTS.get(name, f"Install {name} and try again.") for name in error.names)
    return "\n".join(lines)


def windows_jq_warning() -> str | None:
    if sys.platform != "win32" or shutil.which("jq") is not None:
        return None
    scripts = "\n".join(f"  {script}" for script in JQ_SCRIPTS)
    return (
        "warning: jq not found. Install continues; these forge and ship-pr scripts need it:\n"
        f"{scripts}"
    )
