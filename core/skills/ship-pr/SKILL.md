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
- Never add attribution lines to commits or pull requests.

## 2. Branch and commit

- Create a short kebab-case branch when the current branch is the base branch.
- Before staging or committing, run `bash -n` on every changed `*.sh` file and run `uvx ruff@0.15.10 check --fix --select F,E9 <changed .py files>` when Python files changed. These are the only shipper checks.
- A syntax-check failure blocks the commit. Report the command and its output. Stage any Python file changed by Ruff only when it is in the approved file list.
- Stage only the approved files. Review the staged diff before committing.
- Use an imperative commit subject. Let repository hooks run.
- If a hook changes files, review and stage only those related changes, then retry once.

## 3. Push

- Push with `git push -u origin <branch>`.
- Never force-push unless the user explicitly authorizes it.

## 4. GitHub commands

Read environment variable names from `git config --get aisetup.gh-unset-env`. For every `gh` call, unset each listed name with `env -u <name>`. This supports directory-scoped Git configuration for machines with multiple GitHub accounts. Do not print the values.

Create a non-draft pull request with the resolved base branch. The body should explain what changed, why, and which validations passed. If a pull request already exists for the branch, return its URL instead of creating another.

## 5. Report

Return the pull request URL and resolved base branch. Report any hook or authentication failure with its exact command and concise output.
