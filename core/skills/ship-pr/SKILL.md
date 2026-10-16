---
name: ship-pr
description: Commit approved changes, push a branch, and open or update a pull request.
---

# Ship a pull request

Use this skill only after implementation and validation are complete and the user approved shipping.

## 1. Orient

- Inspect `git status --short`, the current branch, and the `origin` remote.
- Run `bash ~/.claude/skills/ship-pr/scripts/resolve-base-branch.sh <repo>` as one bare whole call (no `cd` prefix, pipe or redirect) and state the result. The Bash tool resets the working directory after every call, so pass the repo path.
- Do not overwrite, stash, or discard unrelated changes.
- Read `references/lessons.md` before the first commit of a session. It is part of this skill.

## 2. Branch and commit

- When the current branch is the base branch, create a short kebab-case branch named for what changed (from `git diff` and `git status`, not file names). Restrict the name to `[a-z0-9-]`: strip or replace every other character before it reaches a command, because it can come from free text.
- Fetch the base and branch from it, so the branch does not start from a stale local copy. Run the fetch as one bare call (no cd prefix, pipe, redirect, `;` or `&&`):

  ```bash
  bash ~/.claude/scripts/git-net.sh -C <repo> fetch origin "<base>"
  git -C <repo> checkout -b "<branch>" "origin/<base>"
  ```

  Between the fetch and the checkout, run `git -C <repo> log --oneline "origin/<base>..HEAD"`. When it prints any commit, the base branch holds unpushed local commits that a branch from `origin/<base>` would leave out. Create no branch, and stop and report those commits.
  Stop and report on either failure: the checkout aborts because the remote base overlaps uncommitted edits (no branch is created and the working tree is untouched), or a branch with that name already exists. Never force-delete or rename around it. Skip this branch step when already on a feature branch.
- Before staging or committing, run `bash -n` on every changed `*.sh` file.
- When Python files changed, run `bash ~/.claude/skills/forge/scripts/gate.sh --print-mode` in the repository. Only when it prints `full` and `uvx` is on the PATH, run `uvx ruff@0.15.10 check --fix --select F,E9 <changed .py files>`. When it prints `none`, run no Python check. When it exits non-zero, report its output and treat the mode as `full`. When the mode is `full` and `uvx` is not on the PATH, skip Ruff and report the skip in the shipper result. These are the only shipper checks.
- A syntax-check failure blocks the commit. Report the command and its output. Stage any Python file changed by Ruff only when it is in the approved file list.
- Stage only the approved files. Review the staged diff before committing.
- Run every `git commit` as `bash ~/.claude/scripts/git-net.sh -C <repo> commit ...`, one bare call: under the Bash sandbox a plain commit fails in repos whose pre-commit hooks need tracked files the sandbox hides.
- After staging, compare the approved list with `git diff --cached --name-only`. Record every approved path that is not staged (hook or permission refusal, ignored, missing, unchanged) with its reason. Do not work around a block. A path already staged as a deletion (`git diff --cached --name-only --diff-filter=D`) and absent from the working tree needs no `git add`; skip it. If any `git add` fails, stop before committing and report the path and the error.
- Changelog check, after staging and before any commit or push, even when nothing is left to commit. You verify; you never write CHANGELOG.md.
  1. List the branch's changed files, committed and staged: `git diff --cached --name-only --no-renames "$(git merge-base origin/<base> HEAD)"`.
  2. Its instruction files are the paths matching `(^|/)CLAUDE(\.fragment)?\.md$`, `(^|/)AGENTS\.md$`, `(^|/)agents/[^/]+\.md$`, `(^|/)skills/.+\.md$` or `(^|/)references/[^/]+\.md$` (the same patterns as `.github/scripts/check_changelog.py`). With none, skip the rest of this check.
  3. With any, both are required: (a) CHANGELOG.md is in that list and `git diff --cached "$(git merge-base origin/<base> HEAD)" -- CHANGELOG.md` adds at least one line starting `- `; (b) the user's OK is on record, as a `USER OK: "<the user's words>"` line in the brief or a `user-ok.md` file in the run dir the brief names.
  4. If either is missing, commit and push nothing and return `NEEDS_CHANGELOG_OK` with the instruction file list and which of (a) and (b) is missing. Leave the staging as it is.
- Ship check, after staging and the Ruff fixes and before any commit or push. Run `python3 ~/.claude/skills/ship-pr/scripts/ship_record.py check --repo <repo> --files <approved files>` as one bare call, adding `--run-dir <run dir>` when the brief names one. It hashes the working tree, which matches the staging for the approved files at this point.
  - `SHIP_RECORD_OK` or `SHIP_RECORD_EXEMPT`: continue.
  - `NEEDS_SHIP_CONFIRM`: unless the brief has a `SHIP ANYWAY: "<the user's words>"` line, commit and push nothing, leave the staging as it is, and return `NEEDS_SHIP_CONFIRM` with the script's line.
  - Files a hook rewrites during a commit retry are not checked again.
- Use an imperative commit subject. Let repository hooks run.
- Keep the staged file list from before each commit attempt. When a commit fails, compare `git status --short` with how it looked before the attempt:
  - A staged file picked up a new unstaged change: a hook rewrote it. Restage only the files staged before the attempt with `git add -u -- <those files>`, never a bare `git add -u`, which is repo-wide and would commit unrelated edits. Retry the same commit, up to 3 attempts in total.
  - Nothing changed: the hook rejects the commit for a real reason. Stop at once, without using the remaining attempts, and report the raw hook output. Never use `--no-verify`.
  - The hook fails on a missing environment variable or token (for example a package registry token): stop without retrying and without `--no-verify`. Report the raw hook output and tell the user the staged files are ready to commit from their own terminal.

## 3. Push

- Before pushing, run the attribution check on unpushed commits. `<range>` is `@{upstream}..HEAD` when the branch has an upstream, else `<base>..HEAD`:

  ```bash
  git log --format='%H%n%B' "<range>" --not "origin/<base>" | grep -inE '^co-authored-by:.*(claude|anthropic)|^claude-session:|generated with \[?claude code|claude\.ai/code/session'
  ```

  It must print nothing. If it prints lines from the last commit, rewrite that commit's message with `bash ~/.claude/scripts/git-net.sh -C <repo> commit --amend -F <file>` as one bare call (no cd prefix, pipe, redirect, `;` or `&&`) and run it again. If older unpushed commits match, stop and report. Never rewrite pushed commits; report matches found in them without blocking.
- Push with `bash ~/.claude/scripts/git-net.sh -C <repo> push -u origin <branch>`. Run every network git command (fetch, pull, push) this way, as one bare call (no cd prefix, pipe, redirect, `;` or `&&`): the Bash sandbox routes ssh through a proxy that git cannot use.
- Never force-push unless the user explicitly authorizes it.

## 4. GitHub commands

Read environment variable names from `git config --get aisetup.gh-unset-env`. For every `gh` call, unset each listed name with `env -u <name>`. This supports directory-scoped Git configuration for machines with multiple GitHub accounts. Do not print the values.

Write the PR title and body to files, never inline in the command: free text with a backtick or `$(...)` would run in the shell. Create the files under `$TMPDIR` (for example in a folder from `mktemp -d "$TMPDIR/ship-pr.XXXXXX"`), never under `/tmp`, which the sandbox refuses. Shell variables do not persist between Bash calls, so use the printed folder path in later calls.

Before `gh pr create` or `gh pr edit`, run the same grep on the PR body file and remove every matching line.

1. Check for an existing pull request with `gh pr view "<branch>" --json url -q .url`.
2. When it succeeds, the pull request exists. Regenerate its body, write it to the body file, run the grep, then run `gh pr edit "<branch>" --body-file <body file>` and go to step 5. Never create a second one.
3. When it fails with a 404 or a "requires the repo scope" error, the `gh` token lacks access. Stop and report that error. `gh pr create` would fail the same way.
4. Otherwise create a non-draft pull request with the resolved base branch: `gh pr create --base "<base>" --head "<branch>" --title "$(cat <title file>)" --body-file <body file>`. Then go to step 5.
5. Wait for the pull request's checks. This is the only step that returns from this section. Note the start time: the wait has a 10-minute deadline. `<number>` is the pull request number, the last part of its URL.
   - Run `gh pr checks <number> --watch --fail-fast --interval 15` with the `env -u` prefix above, as one call. Set its Bash timeout to the time left before the deadline, at most 600000 ms. Each output row is tab-separated: name, state, elapsed time, link. Match the outcomes below in order; the first match wins.
   - Exit code 0: the result line is `checks: passed`.
   - Any row whose state is `fail` or `cancel`: the result line is `checks: failed`, followed by the name and link (columns 1 and 4) of each such row.
   - No check rows in the output, and the output names no authentication, permission, network or HTTP failure: the checks are not registered yet. Wait 30 seconds with `perl -e 'sleep 30'` and run the same command again. After 3 retries or at the deadline, whichever comes first, the result line is `checks: none reported`.
   - Exit code 8 (checks pending) or a Bash timeout: the result line is `checks: pending after 10 min`.
   - Any other error: the result line is `checks: error <first error line>`.
   - No result undoes the push or the pull request. Return the pull request URL and the result line.

## 5. Report

The PR body is written by the shipper on its own pushes only. Nothing refreshes a description after commits land outside ship-pr; rerun ship-pr or edit it by hand. The body holds a summary, the change list and links. No testing-results section unless the caller supplies a PR-body extra section; keep that section verbatim.

When the changelog check failed, return only `NEEDS_CHANGELOG_OK`, the instruction file list and what is missing. When the ship check stopped the ship, return only `NEEDS_SHIP_CONFIRM` and the script's line. Otherwise return the pull request URL, resolved base branch and the check result line from section 4 step 5. State that the attribution check printed nothing. List each unstaged approved file as `<path> - <reason>`, or say `All approved files staged.` Report any hook or authentication failure with its exact command and concise output.

## Edge cases

- Nothing to commit (`git status --porcelain` is empty): when the branch has commits that are not on its upstream or the base (`git log --oneline @{u}..` or `git log --oneline origin/<base>..`), push them and open or point at the pull request as usual. Otherwise say so and stop. Never make an empty commit or open a pull request with no diff.
- The push prints "Everything up-to-date": nothing is new for the pull request. Return the existing link and do not create a second one.
- The repo is missing from `references/base-branches.json`: `resolve-base-branch.sh` falls back to the remote's default branch. Ask only when that also fails.
