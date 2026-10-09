# Gate commands

Forge reads commands from the repository entry in `forge.config.json`. Use only the configured lint, typecheck, migration, test, and Semgrep commands. Do not infer service setup or broaden test scope.

When a command needs credentials or local services, run it through the repository's documented environment wrapper. Never print environment variables. Treat unavailable services as an environmental failure and report the command and concise error.

Repository entries may define `env` for variables exported to every command and `setup` for shell preparation run
before each command. A `testPathRules` entry can override the default test command with `command`; targets from
rules sharing that command are grouped. Test commands may include `<create-db>`, which expands to ` --create-db`
only when the changed files include a Python migration. Every command sees `FORGE_GATE_RUN_ID`, a run-scoped id
of at most 40 characters (the run dir's basename plus a short hash of its path), for naming per-run resources such
as a test database.

Repository entries may define `envFiles`, a list of repository-relative untracked files (for example `.env.local`)
that are copied from the primary worktree into the gate checkout before `setup`. An absent key means none. An entry
that is tracked in the repository or present in the gated commit stops the gate with exit 2.

Repository entries may define `localOnly`, a list of repository-relative fnmatch patterns (`*` also matches `/`)
for tracked or untracked files that are never run files. A repository that tracks session files uses
`"localOnly": ["session/*"]`. Matching paths, and the run dir when it sits inside the repository, are left out of
every diff, of the launch check and the post-ship check, and of `--commit` staging; excluded `--files` entries are
listed in the result's `excludedFiles`. An absent key means none. Unlike `diffExclude`, whose files are still
committed, `localOnly` files are never committed by forge.

`gate.sh --sha <sha> --files <paths>` gates a committed SHA in the run's detached checkout `<runDir>/gate-checkout`
instead of `--repo` in place. The checkout is created once per run and moved between SHAs so installed dependencies
persist; the repository's `worktree` overrides apply there, Semgrep compares against the merge-base of the base
ref and the SHA (`<sha>^` without `--base`), and failure paths are reported relative to the repository.
`gate.sh --base <branch>` starts `gate-<label>.diff` at the merge-base of `origin/<branch>` (or `<branch>` when no
origin ref exists) and HEAD; without it the diff starts at HEAD. Forge's gate and phase-commit calls pass `--base` from the launch's required `base`; gate.sh never resolves or guesses a base itself. Without `--sha`, the gate runs in place. `--no-stages` runs
no stage and is used with `--commit` for phase commits; `--commit` restages and retries once when a pre-commit hook
rewrites files. A run without `--sha` or `--no-stages` runs no stage when a `gate-*.json` in the same run dir passed
with the same `head`, `baseSha` (the merge-base sha), `diffSha256`, `configSha256`, `filesSha256` and
`stageSelection`; its JSON names that result's label in `reusedFrom`. A run without `--base` or any unequal value
runs the stages.

Use `gate.sh --only lint,typecheck,migrations,tests,semgrep,parity` to run selected stages. The JSON result lists
unselected stages in `skipped`. New Semgrep ERROR findings block only for security rules outside test paths; other
new findings are returned in `warnings`. In `full` mode, a repository with Semgrep enabled fails the gate when the
Semgrep binary is not installed; install it or set `"semgrep": false` in that repository's entry.
