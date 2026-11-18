# agent-kit

agent-kit installs a portable Claude Code working environment. It composes a public core, optional modules, a
private overlay, and machine-local settings. It requires Python 3.11+, Git, Bash, jq, and a signed-in Claude Code
CLI. Some modules also require Node.js, Codex, or GitHub CLI.

## Install

```sh
git clone https://github.com/awshumjordan7/agent-kit.git
cd agent-kit
python3 install.py install --yes
```

Run without `--yes` to choose modules and settings. Save and replay the generated profile on another machine:

```sh
python3 install.py install --profile ~/.ai-setup/profile.json --yes
python3 install.py update --check
python3 install.py update
python3 install.py doctor --selfcheck --json
```

`install --dry-run` prints the planned files, preserved unmanaged paths, kept files, settings changes by key path,
and redacted MCP commands without writing them. A managed file you edited is kept: install prints `kept locally
modified` and writes the kit version beside it as `<file>.kit-new`. `settings.json` is merged three ways against the
previous kit render in `~/.ai-setup/settings.base.json`, so keys set by you or Claude Code stay, kit changes apply,
and your value wins a conflict. The home stays in place: only changed files are swapped in, and unmanaged paths are
never moved. Each file the kit replaces or retires is moved to `~/.ai-setup/backups/<timestamp>/claude/<path>`, and
each replaced file outside the Claude home (such as `~/.codex/config.toml`) to `.../<timestamp>/home/<path under your
home>`. A run that replaces nothing prints `no files replaced` and creates no folder. After a successful install,
backup folders older than 30 days are deleted, except the newest 10.
If a swap fails, the files already swapped are put back. When
`--home` is not the default `~/.claude`, install and update skip MCP registration because the Claude CLI always writes
user-scoped servers to the default home. `update` fetches configured layer repositories, replays the profile, and
runs doctor.

## Update

`python3 install.py update --check` reports repositories that are behind and compares managed content with what an
install would write. Files report `missing`, `kit update pending`, `unrecorded`, `conflict`, or `locally modified`
(agent files also name a profile agent override or an unknown source); settings key paths report `kit change pending`,
`conflict (local value kept)`, or `local value kept`; `settings.json` itself can be `missing` or `invalid`; retired
paths report `retired` or `retired but locally modified`. Kept local edits are listed but pass; repository lag or any
other item makes the check exit 1. `python3 install.py update` fetches, composes, installs, reconciles declared MCP
servers, and runs doctor.

## Windows 10 and 11 (native)

agent-kit installs from PowerShell. Install these first:

- Git for Windows. Claude Code runs hooks with its Git Bash; the `bash.exe` in `System32` is the WSL launcher and
  does not count. Set `CLAUDE_CODE_GIT_BASH_PATH` if Git Bash is not in `C:\Program Files\Git\bin`.
- Python 3.11 or newer from python.org, not the Microsoft Store alias.
- Node.js LTS (the firecrawl and context7 MCP servers run through `npx`).
- Claude Code from the native installer (`claude.exe`). Run `claude` once to sign in.

Quit every Claude Code session before you install: Windows cannot replace files a running session holds open.
Then run from the clone:

```powershell
python install.py install
```

Hook commands name the Python that ran the installer, so re-run install after you move or upgrade Python.

Install also gives Claude Code sessions a working `python3`: `~\.claude\bin\python3` runs the Python that ran the
installer, and `env.BASH_ENV` in settings.json points every session bash at `~\.claude\scripts\windows-bash-env.sh`,
which puts that folder first on PATH. Python run that way writes `\n` line endings to pipes; its
`sitecustomize.py` in `~\.claude\scripts\windows-python` hides one your Python install may already have. If your
own settings layer sets `env.BASH_ENV`, install keeps yours and prints a warning. If the Claude home path contains
`$` or a backtick, install skips this step and prints a warning.

Forge runs from chat on native Windows. It needs:

- Git for Windows and python.org Python, as above.
- jq for forge's Codex reviews: `winget install jqlang.jq`. Install prints a warning when jq is missing and carries
  on; the Claude review still runs.
- Codex installed and signed in, for the Codex reviews.

The workflow-maxxing app's forge buttons are not on Windows yet: answer forge's plan approval and questions in chat.

Put personal rules in the local layer, not in the clone, so a `git pull` does not conflict. Create the folder
`~\.ai-setup\local` (install uses it only when it exists) and put `settings.fragment.json` and `CLAUDE.fragment.md`
in it.

## Windows 10 and 11 (WSL2)

WSL2 is the other option on Windows: agent-kit then runs inside WSL2 as on Linux. Use Ubuntu 24.04; Ubuntu 22.04 ships Python 3.10, below the 3.11
floor. Keep the clone and `~/.claude` in the Linux home directory, not under `/mnt/c`. The terminal module is
macOS-only and skips itself on Linux.

```sh
wsl --install -d Ubuntu-24.04
sudo apt update && sudo apt install -y git jq python3 python3-venv curl
```

Run the first command from PowerShell, then open the Ubuntu shell for the rest. Install Node.js LTS (the firecrawl
and context7 MCP servers run through `npx`) and the Claude Code CLI inside WSL, run `claude` once to sign in,
then follow the Install steps above. Install `gh` only for the github module and `codex` only for the codex module.
Verify with:

```sh
python3 install.py doctor --selfcheck --json
claude mcp list
```

## Modules

| Module | Default | Purpose |
|---|---:|---|
| firecrawl | on | web research and crawling |
| context7 | on | current library documentation |
| codex | off | Codex CLI and forge roles |
| playwright | off | browser automation |
| github | off | GitHub CLI and MCP tools |
| marketing | off | market research and content workflows |
| terminal | off | Ghostty defaults on macOS |
| sandbox | off | Claude Code sandbox for Bash on macOS |
| workflow-maxxing | off | status and same-pane handoff for the workflow-maxxing app on macOS, Linux and Windows |

See [docs/profile.md](docs/profile.md) for profile fields and [docs/overlay.md](docs/overlay.md) for private layers.
The local layer lives at `~/.ai-setup/local` and is never committed. Put machine-specific hooks, sounds, webhook
URLs, and permission changes there.

The kit's default session is Opus at xhigh effort. The reviewer and security-advisor agent files use
Fable, so a user without Fable access sets `"model": "opus"` under `agents.reviewer` and
`agents.security-advisor` in the profile.

## Forge lanes

| Lane | Purpose |
|---|---|
| `build` (default) | Investigate, plan, implement, gate, ship, independently review, converge, and hand off. |
| `review` | Review and fix an existing working tree or branch diff. |

Every build plan receives one configured plan review.

For layered releases, merge and tag agent-kit first, then bump the overlay's `requires_agent_kit` pin and run `python3 install.py update`. See [docs/release-order.md](docs/release-order.md).

## Tune

`python3 install.py tune` reads local transcripts and proposes a profile diff. It reports evidence and confidence,
but never changes the installed profile.

## Two GitHub accounts

On a machine with separate work and personal GitHub accounts, use a directory-scoped Git config to tell the shipper which shell tokens must not override the active `gh` login:

```sh
git config aisetup.gh-unset-env "GH_TOKEN GITHUB_TOKEN"
```

The shipper runs every `gh` command through `env -u` for each configured name. Git fetch and push continue to use the repository's SSH remote.

Use Git's `includeIf` to select identity by directory. Use an SSH host alias such as `github-personal` with
`HostName github.com`, `User git`, and the personal `IdentityFile`, then rewrite personal GitHub URLs to that alias.

## Contributing

Open a pull request with a focused change. Public changes must pass the token scanner; maintainers also run the
private denylist before merging external pull requests.
