# Loading repo env vars without printing them

Never `source` an env file in a Bash command. The Bash sandbox denies reads of env files, and
built-in deny rules keep the file tools away from them. Load env vars through the fixed runner
below, or run repository tests through forge's `~/.claude/skills/forge/scripts/gate.sh`.

Recipe:
1. Run the command through the runner, as a whole command with no `cd` prefix:

       bash ~/.claude/scripts/with-env.sh --dir <repo> .envs/.postgres .envs/.django -- env POSTGRES_HOST=localhost <command>

   The runner enters `<repo>`, loads each env file (paths relative to `<repo>`), and runs the
   command after `--`. Put overrides in the command, as `env POSTGRES_HOST=localhost` does above.
   It exits 2 without running the command when an env file is missing or `<repo>` cannot be entered.
   Check the project's service documentation if a connection is refused.
2. Report exit codes, test counts and the deselected count only. Never `echo`, `printenv`, `env`,
   or `set` to inspect what was loaded; if a value's shape matters, report its length.
