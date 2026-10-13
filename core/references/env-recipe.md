# Loading repo env vars without printing them

The env-file hook (`hooks/block_secret_reads.py`) blocks any Bash command whose text names an env
file: `.env`, `.env.<suffix>` other than `.env.example`, `.envrc`, `.env_<suffix>`, or a path in a
`.envs/` folder. Sourcing one inline is blocked too, so never `source` an env file in a Bash
command. Built-in deny rules keep the file tools away from the same files. Load env vars through
the runner script below, or run repository tests through forge's
`~/.claude/skills/forge/scripts/gate.sh`.

Recipe:
1. Write a runner script into the run dir with the Write tool (it checks the path, not the content),
   for example `<runDir>/with-env.sh`:

       #!/usr/bin/env bash
       set -euo pipefail
       REPO="${REPO:-/path/to/project}"
       set -a; . "$REPO/.envs/.postgres"; set +a
       export POSTGRES_HOST=localhost
       exec "$@"

2. Run the command through it: `bash <runDir>/with-env.sh uv run pytest <targets> --create-db`.
   Check the project's service documentation if a connection is refused.
3. Report exit codes, test counts and the deselected count only. Never `echo`, `printenv`, `env`,
   or `set` to inspect what was loaded; if a value's shape matters, report its length.
