# Layered release order

Release changes that affect the private overlay in this order:

1. Merge the agent-kit change and tag the core release.
2. Update the overlay's `requires_agent_kit` pin to that exact tag.
3. Run `python3 install.py update` from the overlay checkout.
4. Verify the installed Forge files match the tagged core plus the overlay allowlist, and run doctor.

Never bump the overlay pin before the core tag exists. The installer resolves the pin during update, so reversing the order can leave an installation on stale core files while presenting current overlay documentation.

## Merging

Merge pull requests without `--admin`, except in the urgent-merge procedure below. When a branch is behind main, update it (`gh pr update-branch <number>`) and merge once its checks pass. Branch protection on main requires the `scan` and `changelog` checks and, with enforce_admins on, applies them to admins too.

Urgent merge that the checks block:

1. Turn enforce_admins off: `gh api -X DELETE repos/<owner>/<repo>/branches/main/protection/enforce_admins`. Save the output in the run dir.
2. Merge with `gh pr merge <number> --admin`. This is the only sanctioned use of `--admin`, and only between steps 1 and 3.
3. Turn it back on: `gh api -X POST repos/<owner>/<repo>/branches/main/protection/enforce_admins`. Save the output in the run dir.

## Tag message

The annotated tag message is the CHANGELOG.md lines added since the previous tag. Nothing in CHANGELOG.md is renamed at release time.

```bash
git diff <prev-tag>..<release commit> -- CHANGELOG.md | sed -n 's/^+- /- /p' > <runDir>/tag-message.txt
git tag -a <tag> -F <runDir>/tag-message.txt <release commit>
```
