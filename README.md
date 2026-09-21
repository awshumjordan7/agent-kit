# agent-kit

agent-kit installs a portable Claude Code working environment. It composes a public core, optional modules, a
private overlay, and machine-local settings. It requires Python 3.11+, Git, Bash, jq, and a signed-in Claude Code
CLI. Some modules also require Node.js, Codex, or GitHub CLI.

## Install

```sh
python3 install.py install --yes
```

Run without `--yes` to choose modules and settings. Save and replay the generated profile on another machine:

```sh
python3 install.py install --profile ~/.ai-setup/profile.json --yes
python3 install.py update --check
python3 install.py update
python3 install.py doctor --selfcheck --json
```

`install --dry-run` prints the planned files, settings, and redacted MCP commands without writing them. Existing
Claude files are backed up before replacement. `update` fetches configured layer repositories, replays the profile,
and runs doctor.

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

Open a pull request with a focused change. Run Ruff and the targeted tests named by the change. Public changes must
pass the token scanner; maintainers also run the private denylist before merging external pull requests.

### CI parity

Run `bash tests/ci_parity.sh` to reproduce the GitHub runner locally before pushing. It runs the pinned Ruff
check, lints workflow YAML with actionlint (skipped if Docker is unavailable), runs the golden tests under a
foreign `$HOME`, and runs the full suite with no `claude` binary on `PATH`. Files the installer copies
verbatim are tracked by hash only; merged and rendered files are stored in full so a review shows their effect.
