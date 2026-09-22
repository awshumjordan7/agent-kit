# Gate commands

Forge reads commands from the repository entry in `forge.config.json`. Use only the configured lint, typecheck, migration, test, and Semgrep commands. Do not infer service setup or broaden test scope.

When a command needs credentials or local services, run it through the repository's documented environment wrapper. Never print environment variables. Treat unavailable services as an environmental failure and report the command and concise error.

Repository entries may define `env` for variables exported to every command and `setup` for shell preparation run
before each command. A `testPathRules` entry can override the default test command with `command`; targets from
rules sharing that command are grouped. Test commands may include `<create-db>`, which expands to ` --create-db`
only when the changed files include a Python migration.

Repository entries may define `envFiles`, a list of repository-relative untracked files (for example `.env.local`)
that are copied from the primary worktree into the gate checkout before `setup`. An absent key means none.

`gate.sh --sha <sha> --files <paths>` gates a committed SHA in the run's detached checkout `<runDir>/gate-checkout`
instead of `--repo` in place. The checkout is created once per run and moved between SHAs so installed dependencies
persist; the repository's `worktree` overrides apply there, Semgrep compares against the run's starting commit, and
failure paths are reported relative to the repository. Without `--sha`, the gate runs in place. `--no-stages` runs
no stage and is used with `--commit` for phase commits; `--commit` restages and retries once when a pre-commit hook
rewrites files.

Use `gate.sh --only lint,typecheck,migrations,tests,semgrep,parity` to run selected stages. The JSON result lists
unselected stages in `skipped`. New Semgrep ERROR findings block only for security rules outside test paths; other
new findings are returned in `warnings`.
