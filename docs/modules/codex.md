# Codex

Disabled by default. Installs the Codex collaboration contract and configuration under `~/.codex` and switches
forge implementation and review roles to their configured Codex models.

Codex reads its global `AGENTS.md` only from `$CODEX_HOME` (default `~/.codex`). Install, update, and doctor's
`codex-agents-sync` check always use `~/.codex/AGENTS.md`. The old `doctor.codex.agents_md` profile setting still
validates but is ignored.

## config.toml updates

Install and update merge `~/.codex/config.toml` key by key, the same way as `settings.json`. The kit data from
the previous install is kept in `~/.ai-setup/codex-config.base.json` (mode 0600). A key the kit changed gets the
new kit value. A key you or Codex changed or added, such as `projects.<path>.trust_level` or `tui.*`, keeps its
local value. When both changed the same key, the local value stays and the key path is reported as a conflict.
Arrays merge as whole values. Output lists key paths only, never values.

When the merge changes nothing, the file is not touched. Otherwise the old file is copied to
`config.toml.backup.<timestamp>` and the merged data is written. The rewrite does not keep blank lines or custom
formatting.

The merge is skipped, and the whole-file rule applies instead, in two cases:

- The live file contains `#` anywhere, because a rewrite would drop comments.
- The live file holds a value the writer cannot write (a date or time, or an array of tables).

Then the live file is kept, the kit version goes to `config.toml.kit-new`, and the reason is printed. The base file
is left as it was, so the kit change is applied on a later install once the cause is removed. A live file that is
not valid TOML is backed up and replaced by the kit version.

`update --check` lists config.toml key changes prefixed with `.codex/config.toml`. A pending kit change counts as
drift; a kept local value does not.
