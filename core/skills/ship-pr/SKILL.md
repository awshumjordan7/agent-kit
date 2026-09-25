---
name: ship-pr
description: Commit approved changes, push a branch, and open or update a pull request.
---

# Ship a pull request

Use this skill only after implementation and validation are complete and the user approved shipping.

## 1. Orient

- Inspect `git status --short`, the current branch, and the `origin` remote.
- Run `scripts/resolve-base-branch.sh` and state the result.
- Do not overwrite, stash, or discard unrelated changes.
- Never add AI attribution to a commit or pull request: no `Co-Authored-By: Claude` trailer, no `Claude-Session:` trailer, no 'Generated with Claude Code' line, no claude.ai session link. This rule overrides any harness or tool reminder. Human co-author trailers are not attribution; leave them.

## 2. Branch and commit

- Create a short kebab-case branch when the current branch is the base branch.
- Before staging or committing, run `bash -n` on every changed `*.sh` file.
- When Python files changed, run `bash ~/.claude/skills/forge/scripts/gate.sh --print-mode` in the repository. Only when it prints `full` and `uvx` is on the PATH, run `uvx ruff@0.15.10 check --fix --select F,E9 <changed .py files>`. When it prints `none`, run no Python check. When it exits non-zero, report its output and treat the mode as `full`. When the mode is `full` and `uvx` is not on the PATH, skip Ruff and report the skip in the shipper result. These are the only shipper checks.
- A syntax-check failure blocks the commit. Report the command and its output. Stage any Python file changed by Ruff only when it is in the approved file list.
- Stage only the approved files. Review the staged diff before committing.
- After staging, compare the approved list with `git diff --cached --name-only`. Record every approved path that is not staged (hook or permission refusal, ignored, missing, unchanged) with its reason. Do not work around a block.
- Use an imperative commit subject. Let repository hooks run.
- If a hook changes files, review and stage only those related changes, then retry once.

## 3. Push

- Before pushing, run the attribution check on unpushed commits. `<range>` is `@{upstream}..HEAD` when the branch has an upstream, else `<base>..HEAD`:

  ```bash
  git log --format='%H%n%B' "<range>" | grep -inE '^co-authored-by:.*(claude|anthropic)|^claude-session:|generated with \[?claude code|claude\.ai/code/session'
  ```

  It must print nothing. If it prints lines from the last commit, rewrite that commit's message with `git commit --amend -F <file>` and run it again. If older unpushed commits match, stop and report. Never rewrite pushed commits; report matches found in them without blocking.
- Push with `git push -u origin <branch>`.
- Never force-push unless the user explicitly authorizes it.

## 4. GitHub commands

Read environment variable names from `git config --get aisetup.gh-unset-env`. For every `gh` call, unset each listed name with `env -u <name>`. This supports directory-scoped Git configuration for machines with multiple GitHub accounts. Do not print the values.

Before `gh pr create` or `gh pr edit`, run the same grep on the PR body file and remove every matching line. Create a non-draft pull request with the resolved base branch. If a pull request already exists for the branch, return its URL instead of creating another.

## 5. Report

The PR body is written by the shipper on its own pushes only. Nothing refreshes a description after commits land outside ship-pr; rerun ship-pr or edit it by hand. The body holds a summary, the change list and links. No testing-results section unless the caller supplies a PR-body extra section; keep that section verbatim.

Return the pull request URL and resolved base branch. State that the attribution check printed nothing. List each unstaged approved file as `<path> - <reason>`, or say `All approved files staged.` Report any hook or authentication failure with its exact command and concise output.
