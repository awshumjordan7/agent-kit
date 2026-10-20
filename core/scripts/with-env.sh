#!/usr/bin/env bash
# Run a command with env files loaded: with-env.sh [--dir DIR] [--done-file FILE] ENV_FILE... -- COMMAND...
# Env files are read relative to DIR. Put overrides in the command, as
# `-- env POSTGRES_HOST=localhost <command>`. Nothing here stops the command printing values.
set -euo pipefail

# Claude Code sets SANDBOX_RUNTIME only in sandboxed Bash calls; any value counts.
if [ -n "${SANDBOX_RUNTIME+x}" ]; then
  echo "with-env.sh must run outside the Bash sandbox, and this call ran inside it. Run it again as one bare Bash call spelled exactly bash ~/.claude/scripts/with-env.sh --dir <repo> <env files> -- <command>: no cd prefix, pipe, redirect, 2>&1, ';' or '&&', with the ~/.claude path as written." >&2
  exit 86
fi

usage() {
  echo "usage: with-env.sh [--dir DIR] [--done-file FILE] ENV_FILE... -- COMMAND..." >&2
  exit 2
}

dir=
done_file=
while [[ ${1:-} == --dir || ${1:-} == --done-file ]]; do
  [[ $# -ge 2 && -n $2 ]] || usage
  if [[ $1 == --dir ]]; then dir=$2; else done_file=$2; fi
  shift 2
done
[[ -z $done_file || $done_file == /* ]] || { echo "with-env.sh: --done-file needs an absolute path: $done_file" >&2; usage; }

if [[ -n $done_file ]]; then
  # A bare call cannot end in "; echo $?", so the script writes the done-file itself.
  trap 'echo "$?" >"$done_file"' EXIT
fi

if [[ -n $dir ]]; then
  CDPATH= cd -- "$dir" 2>/dev/null || { echo "with-env.sh: cannot enter $dir" >&2; usage; }
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
if [[ -n $done_file ]]; then
  "$@"
else
  exec "$@"
fi
