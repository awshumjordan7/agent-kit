Bash runs in a macOS sandbox. "Operation not permitted" on an env file or credential folder is by design: report it and never look for another way to the file.
Network git runs as `bash ~/.claude/scripts/git-net.sh -C <repo> <git args>`. Commands that need env files run as `bash ~/.claude/scripts/with-env.sh --dir <repo> <env files> -- <command>`.
These and the other excluded scripts leave the sandbox only as a whole command spelled with `~/.claude/...`. A `cd <dir> &&` prefix, a chain or a redirection keeps them inside.
Read `.env.example` with the Read tool.
Temporary files go under `$TMPDIR` (`mktemp -d "$TMPDIR/x.XXXXXX"`). Plain `mktemp` and other `/tmp` paths are denied.
