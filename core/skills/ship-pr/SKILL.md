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

## 2. Branch and commit

- Create a short kebab-case branch when the current branch is the base branch.
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
- Use an imperative commit subject. Let repository hooks run.
- If a hook changes files, review and stage only those related changes, then retry once.

## 3. Push

- Before pushing, run the attribution check on unpushed commits. `<range>` is `@{upstream}..HEAD` when the branch has an upstream, else `<base>..HEAD`:

  ```bash
  git log --format='%H%n%B' "<range>" --not "origin/<base>" | grep -inE '^co-authored-by:.*(claude|anthropic)|^claude-session:|generated with \[?claude code|claude\.ai/code/session'
  ```

  It must print nothing. If it prints lines from the last commit, rewrite that commit's message with `bash ~/.claude/scripts/git-net.sh -C <repo> commit --amend -F <file>` and run it again. If older unpushed commits match, stop and report. Never rewrite pushed commits; report matches found in them without blocking.
- Push with `bash ~/.claude/scripts/git-net.sh -C <repo> push -u origin <branch>`. Run every network git command (fetch, pull, push) this way, as a whole command: the Bash sandbox routes ssh through a proxy that git cannot use.
- Never force-push unless the user explicitly authorizes it.

## 4. GitHub commands

Read environment variable names from `git config --get aisetup.gh-unset-env`. For every `gh` call, unset each listed name with `env -u <name>`. This supports directory-scoped Git configuration for machines with multiple GitHub accounts. Do not print the values.

Before `gh pr create` or `gh pr edit`, run the same grep on the PR body file and remove every matching line. Create a non-draft pull request with the resolved base branch. If a pull request already exists for the branch, return its URL instead of creating another.

## 5. Report

The PR body is written by the shipper on its own pushes only. Nothing refreshes a description after commits land outside ship-pr; rerun ship-pr or edit it by hand. The body holds a summary, the change list and links. No testing-results section unless the caller supplies a PR-body extra section; keep that section verbatim.

When the changelog check failed, return only `NEEDS_CHANGELOG_OK`, the instruction file list and what is missing. Otherwise return the pull request URL and resolved base branch. State that the attribution check printed nothing. List each unstaged approved file as `<path> - <reason>`, or say `All approved files staged.` Report any hook or authentication failure with its exact command and concise output.
