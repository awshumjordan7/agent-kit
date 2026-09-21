#!/usr/bin/env bash
# Resolve the correct PR base branch for the repo in the current working directory.
#
# Looks up references/base-branches.json by "owner/repo" slug (parsed from the
# `origin` remote). If the repo isn't listed, falls back to the remote's actual
# default branch via `git ls-remote --symref`, which talks plain git/SSH and
# doesn't need any GitHub API scope — unlike `gh repo view`, which can 404 if
# the active `gh` account lacks the `repo` scope for a private repo.
set -euo pipefail

run_gh() {
  local configured name
  local env_args=()
  configured="$(git config --get aisetup.gh-unset-env || true)"
  for name in $configured; do
    env_args+=("-u" "$name")
  done
  env "${env_args[@]}" gh "$@"
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG="$SCRIPT_DIR/../references/base-branches.json"

REMOTE_URL="$(git remote get-url origin)"
SLUG="$(echo "$REMOTE_URL" | sed -E 's#^git@github\.com:##; s#^https://github\.com/##; s#\.git$##')"

BASE=""
if [ -f "$CONFIG" ]; then
  # --arg binds $SLUG as a jq variable rather than interpolating it into source
  # text, and a jq parse failure is distinct from "key not found" (empty
  # string) — don't let a corrupted config silently fall through to the
  # generic default when it's supposed to be overriding that default.
  if ! BASE="$(jq -r --arg slug "$SLUG" '.[$slug].branch // empty' "$CONFIG" 2>&1)"; then
    echo "base-branches.json exists but jq couldn't parse it — fix the file, don't silently fall back to the repo default. jq said: $BASE" >&2
    exit 1
  fi
fi

if [ -z "$BASE" ]; then
  BASE="$(git ls-remote --symref origin HEAD 2>/dev/null | awk '/^ref:/ {sub("refs/heads/", "", $2); print $2}')"
fi

if [ -z "$BASE" ] && command -v gh >/dev/null 2>&1; then
  BASE="$(run_gh repo view "$SLUG" --json defaultBranchRef -q .defaultBranchRef.name)"
fi

if [ -z "$BASE" ]; then
  echo "Could not resolve a base branch for $SLUG — check manually (e.g. 'gh repo view') or ask the user." >&2
  exit 1
fi

echo "$BASE"
