#!/usr/bin/env bash
# The Claude Code sandbox routes ssh through a proxy that git cannot use, so network
# git (push, fetch, pull, clone, ls-remote) runs outside it through this script.
# Local commits use it too, because pre-commit hooks may need tracked files the sandbox hides.
# Branch checkouts use it because a sandboxed checkout cannot write tracked env files such as .envrc.
# Claude Code sets SANDBOX_RUNTIME only in sandboxed Bash calls; any value counts.
if [ -n "${SANDBOX_RUNTIME+x}" ]; then
  echo "git-net.sh must run outside the Bash sandbox, and this call ran inside it. Run it again as one bare Bash call spelled exactly bash ~/.claude/scripts/git-net.sh -C <repo> <git args>: no cd prefix, pipe, redirect, 2>&1, ';' or '&&', with the ~/.claude path as written." >&2
  exit 86
fi
unset GIT_SSH_COMMAND
exec git "$@"
