# Changelog

One line per instruction change. A change adds its lines under today's `## YYYY-MM-DD`
heading, creating it at the top if missing. Each line reads `- <paths or area>: <reason in one sentence>`.

## 2026-10-14
- core/skills/forge (forge-core.js, SKILL.md, references): remove the automatic browser QA stage (sandbox QA, browser smoke, QA draft, post-fix refresh); QA now runs by hand with the stage docs, and the profile keys stages.sandbox and stages.qa_login are accepted and ignored.
- core/skills/forge: remove STATUS.json and status_merge.py; the handoff builds its Manual QA checklist from the acceptance criteria.
- core/skills/forge: plan-facts returns the acceptance criteria in the same call, and forgeConfig is now a required launch argument (the config reader agent is gone).
- core/skills/forge: the pre-ship checkpoint writes a smoke check on Opus medium instead of recommending ship, smoke or QA, and forge runs that smoke in the foreground before the pause and fails it when it changes the working tree; checkpoint.json drops recommendation, decidedBy and the plan hash.
- core/skills/forge: remove gate.sh --push, the parity stage, the inline gate diff, the implementation-summary file, reviewer disputes and triage-template.md.
- modules/sandbox: a new macOS-only module turns on Claude Code's sandbox for Bash, which blocks env-file and credential-folder reads at the operating-system level.
- core/hooks, core/settings.fragment.json, tests/secret_hook, .github/workflows/secret-hook.yml: the env-file hook and its tests are removed; the sandbox module replaces it.
- core/scripts, core/skills/ship-pr, core/skills/forge, core/references/env-recipe.md, core/agents/worker.md: network git and env-loaded commands go through two fixed scripts that run outside the sandbox.
- core/skills/forge/scripts/codex-exec.sh: the wrapper stops with one line instead of waiting forever when its lock folder cannot be created.
- core/layer.toml: register the sandbox module so the installer loads it when the profile turns it on.

## 2026-10-13
- core/hooks (block_secret_reads.py), core/settings.fragment.json: the regex secret-read hook is replaced by a check that blocks only Bash commands naming an env file and Artifact uploads of one; built-in deny rules cover the file tools.
- core/scripts (exposure_scan.py): a weekly scanner logs where secret-shaped values appeared in transcripts, without the values.
- core/CLAUDE.md, core/references/env-recipe.md, core/agents/worker.md, modules/marketing/skills/market-research: drop rules that existed only for the old hook's word heuristics and the inline sourcing route.
- core/skills/forge/references (cost-controls.md): mark the gpt-6-astra note as history so the model-name check, now canonical on 6.1, passes.
- core/hooks (ask_register.py), core/scripts/handoff.py, core/settings.fragment.json, aisetup/profile.py: the ask register start hook and handoff check are removed; no project on this machine used them, and ask_register_projects is now ignored.
- core/settings.fragment.json, core/CLAUDE.md, core/agents (shipper.md, worker.md), core/skills/ship-pr (SKILL.md), core/skills/forge/references (forge-core.js): attribution is turned off in settings, so the prose reminders to omit AI attribution are removed.
- core/hooks (doctor_daily.py, feedback_inbox.py), core/settings.fragment.json, aisetup/profile.py, core/profile.default.json, docs/profile.md: the doctor_daily and feedback_inbox hooks are removed because updates are manual, and the auto_update profile key is now ignored.
- core/settings.fragment.json: the skill-creator and pr-review-toolkit plugin entries are removed from enabledPlugins because they are unused.
- core/agents (reviewer.md), core/skills/forge/references (forge-core.js, cost-controls.md): the forge reviewer and checkpoint run on Fable at high effort, with an Opus xhigh fallback if Fable returns nothing.
- core/profile.default.json, core/skills/forge/references (cost-controls.md), modules/codex: Codex review runs on gpt-6.1-sol instead of gpt-6-sol.
- modules/memory, modules/codex (config.toml), core (layer.toml, profile.default.json), README.md: the memory module and the Codex context7 server are removed.
- core/hooks (context_guard.py): the context guard sends one notice at 280k tokens and no longer blocks Stop, replacing the 225k, 250k and 275k bands.
- core/hooks (block_secret_reads.py): the Artifact tool now blocks secret files passed through its `file_paths` and `files` arguments, which slipped past the old check (C-003).
- core/CLAUDE.md: a sub-agent puts the optimizing-workflow entry's path in its final message instead of messaging the session (C-135).
- core/skills/forge/references (claude-reviewer-contract.md): remove the stale manual-round review policy from the reviewer prompt, which the reviewer cannot act on (C-039).
- core/skills/forge/references (implement-mode.md, triage-template.md): point at `forge build` and the `build` lane verdict instead of the retired `forge dev`, QUICK and ESCALATE_TO_DEV names (C-044).
- core/skills/forge/references (build-lane.md): the checkout may be on the base branch or detached, as ship-pr does (C-180).
- core/skills/forge (forge-core.js, run_context.py): read phases.json through the digest-checked facts command, so an echo that changes a value is retried instead of trusted.

## 2026-10-09
- core/hooks (block_secret_reads.py): Read/Write/Edit block on credential-shaped files, secret paths and secrets/credentials folders instead of any bare credential word; /app/env.sh counts as an env file, and sourcing it for a run passes; grep -q/-c/-l on env files passes; 15 harmless Bash shapes no longer block; block messages name a working route.
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
