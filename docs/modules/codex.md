# Codex

Disabled by default. Installs the Codex collaboration contract and configuration under `~/.codex` and switches
forge implementation and review roles to their configured Codex models.

Codex reads its global `AGENTS.md` only from `$CODEX_HOME` (default `~/.codex`). Install, update, and doctor's
`codex-agents-sync` check always use `~/.codex/AGENTS.md`. The old `doctor.codex.agents_md` profile setting still
validates but is ignored.
