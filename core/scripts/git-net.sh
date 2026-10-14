#!/usr/bin/env bash
# The Claude Code sandbox routes ssh through a proxy that git cannot use, so network
# git (push, fetch, pull, clone, ls-remote) runs outside it through this script.
# Local commits use it too, because pre-commit hooks may need tracked files the sandbox hides.
unset GIT_SSH_COMMAND
exec git "$@"
