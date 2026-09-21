# Loading repo env vars without printing them

The cred-read hook (`hooks/block_secret_reads.py`) blocks any Bash command whose text reads or
sources a credential path (`.envs/`, `.env.*`, `.pgpass`, ...). Do not `source` an env file in a
Bash command, and do not pipe a heredoc that sources one into `bash`. Heredocs that only mention
a path in prose are allowed.

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
