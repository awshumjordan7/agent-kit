#!/usr/bin/env bash
# Run a command with env files loaded: with-env.sh [--dir DIR] ENV_FILE... -- COMMAND...
# Env files are read relative to DIR. Put overrides in the command, as
# `-- env POSTGRES_HOST=localhost <command>`. Nothing here stops the command printing values.
set -euo pipefail

usage() {
  echo "usage: with-env.sh [--dir DIR] ENV_FILE... -- COMMAND..." >&2
  exit 2
}

if [[ ${1:-} == --dir ]]; then
  [[ $# -ge 2 ]] || usage
  cd "$2" 2>/dev/null || { echo "with-env.sh: cannot enter $2" >&2; exit 2; }
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
  # Inside the sandbox a denied env file fails this test too.
  [[ -f $file && -r $file ]] || { echo "with-env.sh: env file not found or not readable: $file" >&2; exit 2; }
  # shellcheck disable=SC1090
  source "$file" || { echo "with-env.sh: cannot load $file" >&2; exit 2; }
done
set +a
exec "$@"
