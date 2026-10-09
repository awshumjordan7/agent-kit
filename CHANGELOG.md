# Changelog

One line per instruction change. A change adds its lines under today's `## YYYY-MM-DD`
heading, creating it at the top if missing. Each line reads `- <paths or area>: <reason in one sentence>`.

## 2026-10-09
- core/skills/forge (forge-core.js, run_context.py, gate.sh): drop baseline.json; a fresh build launch needs a clean tree with no commits ahead of the base branch, and Ship stops when run files are left uncommitted (C-198).
- core/skills/forge/SKILL.md and references (build-lane.md, gate-commands.md): diffs and the Semgrep base start at the merge-base with the base branch; a new `localOnly` gate key keeps tracked local files out of every run, including phase commits.
- core/skills/forge (SKILL.md, forge-core.js, run_context.py): forge launches now require base, resolved by the main session with resolve-base-branch.sh, with no silent fallback to main (C-198).

## 2026-10-08
- core/CLAUDE.md: cut duplicated and narrow text (routing table to a pointer, artifacts and handoff duplicates); replace the fan-out cap with "no cap; batch parallel sub-agents into one Workflow".
- modules/marketing: fragment removed; its rule now lives in the two marketing skills that use it.
- core/agents (locator, triage, scout, worker): skip CLAUDE.md to cut start tokens (estimated 3.7k per run, not yet measured); scout and worker carry their own secret, contract-capture and repo-conventions lines, worker also an attribution line and a code-standards pointer, and locator a secret line.
- core/skills/ship-pr, forge, brainstorming: instruction changes need the user's OK on record and a CHANGELOG line.
- core/skills/forge/references/code-standards.md: regenerated from CLAUDE.md; it had lacked the Tests section's approved-tests and gate-none paragraph since #40.
- CHANGELOG.md: history before this change is in git log and docs/intentional-changes.md.
