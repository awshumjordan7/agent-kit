# Changelog

One line per instruction change. A change adds its lines under today's `## YYYY-MM-DD`
heading, creating it at the top if missing. Each line reads `- <paths or area>: <reason in one sentence>`.

## 2026-10-09
- core/hooks (block_secret_reads.py): Read/Write/Edit block on credential-shaped files, secret paths and secrets/credentials folders instead of any bare credential word; /app/env.sh counts as an env file; grep -q/-c/-l on env files passes; 15 harmless Bash shapes no longer block; block messages name a working route.
- core/references/env-recipe.md: a relative `set -a; . .envs/<file>; set +a` is allowed; absolute paths use the runner script.
- core/CLAUDE.md: name your own files without credential words.
- core/skills/forge (forge-core.js, run_context.py, build-lane.md, SKILL.md): when every changed file is docs, instruction text or config, the pre-ship checkpoint agent is skipped (fixed ship recommendation, the run still pauses) and the Codex reviewer is skipped unless an instruction file changed.
- core/skills/forge (forge-core.js): decisions.md names the reviewer and severity on each dropped and confirmed review finding; forge-stats.py removed (no callers).
- core/skills/forge (forge-core.js, run_context.py, gate.sh): drop baseline.json; a fresh build launch needs a clean tree with no commits ahead of the base branch, and Ship stops when run files are left uncommitted (C-198).
- core/skills/forge/SKILL.md and references (build-lane.md, gate-commands.md): diffs and the Semgrep base start at the merge-base with the base branch; a new `localOnly` gate key keeps tracked local files out of every run, including phase commits.
- core/skills/forge (SKILL.md, forge-core.js, run_context.py): forge launches now require base, resolved by the main session with resolve-base-branch.sh, with no silent fallback to main (C-198).
- core/CLAUDE.md (Plain English): add five rules borrowed from ASD-STE100 Simplified Technical English (one idea per sentence with a 25-word cap, at most three nouns in a row and no semicolons, lists for steps and three or more items, and keep facts and certainty when rewriting a source) to tighten plain-English answers.
- core/skills/forge (SKILL.md, references/plan-review-prompt.md): a plan that calls or changes another repository's or an external service's interface lists each seam with its provider and the source of its shape, fixtures come from that source, and plan review checks it (SDD idea 1, N-04).
- modules/codex (data/forge.json, docs/modules/codex.md): with the codex module on, plan review runs on Codex gpt-6.1-sol at xhigh; without it plan review stays on Claude Opus xhigh.

## 2026-10-08
- core/CLAUDE.md: cut duplicated and narrow text (routing table to a pointer, artifacts and handoff duplicates); replace the fan-out cap with "no cap; batch parallel sub-agents into one Workflow".
- modules/marketing: fragment removed; its rule now lives in the two marketing skills that use it.
- core/agents (locator, triage, scout, worker): skip CLAUDE.md to cut start tokens (estimated 3.7k per run, not yet measured); scout and worker carry their own secret, contract-capture and repo-conventions lines, worker also an attribution line and a code-standards pointer, and locator a secret line.
- core/skills/ship-pr, forge, brainstorming: instruction changes need the user's OK on record and a CHANGELOG line.
- core/skills/forge/references/code-standards.md: regenerated from CLAUDE.md; it had lacked the Tests section's approved-tests and gate-none paragraph since #40.
- CHANGELOG.md: history before this change is in git log and docs/intentional-changes.md.
