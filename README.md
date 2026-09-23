# agent-kit

agent-kit installs a portable Claude Code working environment. It composes a public core, optional modules, a
private overlay, and machine-local settings. It requires Python 3.11+, Git, Bash, jq, and a signed-in Claude Code
CLI. Some modules also require Node.js, Codex, or GitHub CLI.

## Install

```sh
git clone https://github.com/awshumjordan7/agent-kit.git ~/agent-kit
cd ~/agent-kit
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
and your value wins a conflict. The previous home becomes a backup, unmanaged paths are moved back into the new
home, and the backup keeps only files that were replaced or retired; an empty backup is removed. When `--home` is not
the default `~/.claude`, install and update skip MCP registration because the Claude CLI always writes user-scoped
servers to the default home. `update` fetches configured layer repositories, replays the profile, and runs doctor.

## Update

`python3 install.py update --check` reports repositories that are behind and compares managed content with what an
install would write. Files report `missing`, `kit update pending`, `unrecorded`, `conflict`, or `locally modified`
(agent files also name a profile agent override or an unknown source); settings key paths report `kit change pending`,
`conflict (local value kept)`, or `local value kept`; `settings.json` itself can be `missing` or `invalid`; retired
paths report `retired` or `retired but locally modified`. Kept local edits are listed but pass; repository lag or any
other item makes the check exit 1. `python3 install.py update` fetches, composes, installs, reconciles declared MCP
servers, and runs doctor.

## Windows 10 and 11 (WSL2)

agent-kit runs inside WSL2, not in PowerShell. Use Ubuntu 24.04; Ubuntu 22.04 ships Python 3.10, below the 3.11
floor. Keep the clone and `~/.claude` in the Linux home directory, not under `/mnt/c`. The terminal module is
macOS-only and skips itself on Linux.

```sh
wsl --install -d Ubuntu-24.04
sudo apt update && sudo apt install -y git jq python3 python3-venv curl
```

Run the first command from PowerShell, then open the Ubuntu shell for the rest. Install Node.js LTS (the firecrawl,
context7, and memory MCP servers run through `npx`) and the Claude Code CLI inside WSL, run `claude` once to sign in,
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
| memory | on | persistent local knowledge |
| codex | off | Codex CLI and forge roles |
| playwright | off | browser automation |
| github | off | GitHub CLI and MCP tools |
| marketing | off | market research and content workflows |
| terminal | off | Ghostty defaults on macOS |

See [docs/profile.md](docs/profile.md) for profile fields and [docs/overlay.md](docs/overlay.md) for private layers.
The local layer lives at `~/.ai-setup/local` and is never committed. Put machine-specific hooks, sounds, webhook
URLs, and permission changes there.

## Forge lanes

| Lane | Purpose |
|---|---|
| `build` (default) | Investigate, plan, implement, gate, ship, independently review, converge, and hand off. |
| `review` | Review and fix an existing working tree or branch diff. |

`quick` and `dev` are temporary aliases for `build`. Every build plan receives one configured plan review.

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
