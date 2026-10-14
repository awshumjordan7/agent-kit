#!/usr/bin/env bash
# Run a command with env files loaded: with-env.sh [--dir DIR] ENV_FILE... -- COMMAND...
# Env files are read relative to DIR. Put overrides in the command, as
# `-- env POSTGRES_HOST=localhost <command>`. Nothing here stops the command printing values.
set -euo pipefail

# Claude Code sets SANDBOX_RUNTIME only in sandboxed Bash calls; any value counts.
if [ -n "${SANDBOX_RUNTIME+x}" ]; then
  echo "with-env.sh must run outside the Bash sandbox, and this call ran inside it. Run it again as one bare Bash call spelled exactly bash ~/.claude/scripts/with-env.sh --dir <repo> <env files> -- <command>: no cd prefix, pipe, redirect, 2>&1, ';' or '&&', with the ~/.claude path as written." >&2
  exit 86
fi

usage() {
  echo "usage: with-env.sh [--dir DIR] ENV_FILE... -- COMMAND..." >&2
  exit 2
}

if [[ ${1:-} == --dir ]]; then
  [[ $# -ge 2 ]] || usage
  CDPATH= cd -- "$2" 2>/dev/null || { echo "with-env.sh: cannot enter $2" >&2; usage; }
  shift 2
fi

files=()
while [[ $# -gt 0 && $1 != -- ]]; do
  files+=("$1")
  shift
done
[[ $# -gt 0 ]] && shift
[[ ${#files[@]} -gt 0 && $# -gt 0 ]] || usage

set -a
for file in "${files[@]}"; do
  [[ $file == */* ]] || file=./$file
  # Inside the sandbox a denied env file fails this test too.
  [[ -f $file && -r $file ]] || { echo "with-env.sh: env file not found or not readable: $file" >&2; usage; }
  # shellcheck disable=SC1090
  source "$file" || { echo "with-env.sh: cannot load $file" >&2; usage; }
done
set +a
exec "$@"
