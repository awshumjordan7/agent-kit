---
name: precommit-hook-env-failure
description: >-
  Use when `git commit` fails because a pre-commit hook (husky, lefthook, pre-commit) is missing an env var, tool, or registry auth that the user's interactive shell has, for example "Environment variable not found (GITHUB_TOKEN)", "command not found" for yarn/pnpm/bun, or a registry 401. Not for hooks that fail on real lint, type, or test errors.
---

# Pre-commit Hook Environment Failure

When a pre-commit hook fails because Claude's Bash shell is missing an env var or auth that the user's interactive terminal has, **never silently bypass with `--no-verify`.** Surface the failure and offer the user three paths.

## Why this happens

The Bash tool runs commands in a fresh, non-interactive shell. It does **not** source the user's `~/.zshrc`, `~/.bashrc`, `~/.zshenv`, `~/.profile`, or any private dotfiles. So:

- `GITHUB_TOKEN` set in `~/.zshrc` → not present in Bash tool
- `npmrc` auth tokens loaded by shell init → not present
- `keychain`-managed SSH agents, AWS profiles, GCP creds → not present
- Custom `PATH` additions for tools installed in user-local dirs → not present

Pre-commit hooks (husky/lefthook/etc.) inherit whatever shell launched them. When `git commit` runs from the Bash tool, the hook also lacks those env vars. When the hook calls `yarn fix && yarn tsc --noEmit` and `.yarnrc.yml` requires `GITHUB_TOKEN` for private packages, yarn refuses to run. The hook exits non-zero. Commit fails.

This is **not a code defect** — the user's interactive `git commit` would succeed. It is purely an environment mismatch.

## What to do

When you detect this failure mode (look for: `Environment variable not found`, `Unable to authenticate`, `command not found` for a tool the user clearly has, `401 Unauthorized` from a registry, husky/lefthook reporting a failure code from a yarn/npm/pnpm subprocess), surface the issue to the user and offer **three paths**, in this order:

### Path 1 — User runs the commit themselves (default recommendation)

Files are already staged. Give the user a copy-pasteable command for their terminal:

```bash
git commit -m "<message>" && git push
```

Their interactive shell has the missing env, so the hook will succeed.

### Path 2 — User uses `!` prefix to inherit their shell environment

The user can type `! git commit -m "..." && git push` directly in the Claude Code prompt. The `!` prefix runs the command in their interactive shell session, which has the env vars. Output flows back into the conversation.

### Path 3 — Explicit `--no-verify` authorization

Only if the user **explicitly** asks ("use no-verify", "skip the hook", "bypass it"). Per default Claude Code policy, never skip hooks without explicit user request. When the user does request it:

- Before committing with `--no-verify`, run the checks the hook runs (for example `yarn tsc --noEmit`) and report each result as it came out. They often need the same missing env var; if a check cannot run, say so, so the user decides knowing it did not run.
- Run `git commit --no-verify -m "<message>"` from the Bash tool.
- Do not assume future commits also have `--no-verify` authorization. The authorization is single-use unless the user says otherwise.

## Example response

```
The pre-commit hook ran `yarn fix && yarn tsc --noEmit` and yarn failed with
"Environment variable not found (GITHUB_TOKEN)". Your interactive terminal has
this set; my Bash shell doesn't.

Files are staged. Three paths:

1. **Run it yourself in your terminal:**
   ```bash
   git commit -m "<msg>" && git push
   ```

2. **Use `! git commit ...`** in this prompt — runs in your shell, output comes back here.

3. **Authorize `--no-verify`** — I would run tsc + eslint myself first and report
   what they show (or that they cannot run here). Say "use no-verify" if you want me to commit from here.
```

## Do This

- Surface the actual error message verbatim so the user sees what failed.
- Report the result of any check you ran outside the hook (`tsc`, `eslint`, etc.), and name any check you could not run. The user weighs path 3 with that result.
- Offer all three paths in the same message; let the user choose.
- Default-recommend path 1 (interactive shell). It is the lowest-risk option.
- Remember the staged state. If the user picks path 1, the files are already `git add`-ed.

## Don't Do This

- **Never** silently retry with `--no-verify`. The user explicitly hasn't authorized that.
- Don't try to source `~/.zshrc` or set the env var yourself unless you have explicit permission and a known-safe value. Tokens are sensitive.
- Don't blame the user's setup — this is a Bash-tool-vs-interactive-shell architectural quirk, not user error.
- Don't assume the hook is wrong and suggest removing it. The hook is doing its job; the env mismatch is the problem.
- Don't propose a workaround that disables the hook permanently (e.g., editing husky config). The user wants their pre-commit gates.

## Negative triggers

- Hook fails because of an actual lint/type/test error → fix the code, not the hook
- Hook fails because the user lacks GPG signing config → that's a different problem
- Hook fails because of file permissions → that's a different problem
- User says "stop running hooks for this whole session" → that's a settings change, escalate
