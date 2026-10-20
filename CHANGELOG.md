# Changelog

One line per instruction change. A change adds its lines under today's `## YYYY-MM-DD`
heading, creating it at the top if missing. Each line reads `- <paths or area>: <reason in one sentence>`.
When a change fixes an inbox entry, cite its id (I-xxx or C-xxx) in the CHANGELOG line.

## 2026-10-19
- modules/sandbox (module.toml, CLAUDE.fragment.md), aisetup (manifest.py, layers.py, deps.py, selfcheck.py), install.py, README.md, docs/modules/sandbox.md: the sandbox module installs on Linux and WSL2. A new `requires_platform` module key makes the install stop when bubblewrap or socat is missing. Selfcheck reports missing sandbox dependencies, and install.py refuses native Windows.
- core/skills/forge/scripts/codex-exec.sh: the printed watch command uses the `~/.claude` spelling, so it runs outside the sandbox as printed (here-0630, here-0631).
- core/scripts/with-env.sh, core/agents/worker.md: `--done-file` writes the exit code, since a bare call cannot end in `; echo $?` (here-0632).
- core/references/brief-template.md: briefs mark every excluded-script call as bare (here-0616) and check servers by port on macOS, not with pgrep or ps (here-0617).
- core/agents/browser.md: credentials are read one value at a time with jq or printenv, never with Read or cat (here-0614).
- core/scripts/serve_dir.py, core/agents/browser.md, core/references/brief-template.md, modules/sandbox/settings.fragment.json, README.md: local previews are served by an excluded script on 127.0.0.1, so Playwright MCP reaches them on Linux and WSL2 too (PR #93 review).
- core/skills/forge/scripts/run_context.py, core/skills/forge/scripts/gate.sh, core/skills/forge/references/gate-commands.md: `--base` prefers `origin/<base>` only for a remote branch name, so `--base HEAD` (and in run_context.py `HEAD~n` or a sha) diffs from that commit instead of the whole branch (here-0610, -0612, -0613, -0618).
- core/skills/forge/scripts/build-code-review-prompt.sh, core/skills/forge/references/codex-wrapper.md: say what each `--base` form reviews, and give the `git show --cc --format=` merge-review recipe.
- core/skills/forge/scripts/codex-exec.sh: `--inline-diff` accepts a combined merge diff that starts with `diff --cc` (here-0627).
- modules/sandbox/settings.fragment.json: drop the `~/.config/gh` credentials deny, because Claude Code 2.1.304 lets it override the `allowRead` entries for config.yml and hosts.yml, so every sandboxed `gh` call failed to read its config.

## 2026-10-16
- core/skills/forge/scripts/gate.sh: `--commit` stages a tracked file that matches .gitignore instead of silently dropping it (I-368).
- aisetup/cli.py: install and update warn on stderr when a later layer replaces an earlier layer's file with different content (I-122).
- core/skills/forge/references/forge-core.js: the cross-model BLOCKED text names the cause line and the resumeAttempt relaunch (I-104); a resume gates re-queued phases and the final gate at the branch HEAD, so a manual fix is checked (I-344); a run with no ticket links no Jira ticket (I-031).
- core/skills/forge (forge-core.js, SKILL.md, references/build-lane.md, codex-wrapper.md, cost-controls.md): remove the pre-ship smoke writer, which found 0 real defects in 12 stops; the run still pauses at PRE_SHIP, and `checkpointDecision` smoke with `smokeCommand` runs a named check.
- core/agents/worker.md, core/agents/scout.md: the done-file wait rule now lives in the agent files, since both agents skip CLAUDE.md; scouts run only foreground commands (I-003).
- core/agents/browser.md, core/agents/claude-implementer.md: browser writes one NOT RUN row per check before it starts and updates each row as it goes, so a turn cap keeps every finished check (I-016); implementers never run `git stash`, since linked worktrees share one stash list (I-320).
- core/references/state-template.md: STATE.md stays under about 30 KB with finished history moved to decisions.md (I-035); a QA verdicts line comes only from a qa-results read made in the session (I-113).
- core/skills/forge/references/forge-core.js, core/skills/forge/scripts/run_context.py: a turn-capped agent no longer aborts the build lane (I-401); ghEnvUnset matches worktree folder names (I-438); Bot Review compares repo names, not owner/name with a bare name (I-326); ship prompts use the launch base branch (I-449); the smoke writer gets the gate's test templates (I-398); read-plan checks the plan path it read (I-439).
- core/skills/ship-pr/SKILL.md, core/agents/shipper.md, forge-core.js SHIP_SCHEMA: after opening or updating a PR the shipper waits up to 10 minutes for its checks and reports failures (I-127).
- core/skills/forge/references/implement-mode.md, core/skills/ship-pr/scripts/ship_record.py: implement-mode runs are not exempt from the ship check; only build and review lanes are, because they ship before review (I-432).
- core/scripts/handoff.py, core/scripts/drift_report.py, modules/sandbox: drop the goal-change diff, the drift metrics files, drift_report.py and its review reminder; the handoff keeps the user log, the entry count and the section refusal, and counts `- [open ...]` questions with any suffix.
- modules/sandbox/CLAUDE.fragment.md: `git worktree add` and `remove` run through git-net.sh, because a sandboxed checkout cannot write tracked env files (I-424). Briefs name only the global with-env.sh, since a run-dir copy stays sandboxed (I-426).
- core/references/brief-template.md: OUTPUT paths are absolute and checked with `ls` before the final message (I-421, I-435). `gate.sh --files` takes one argument per path, quoted when needed, or one comma-separated argument (I-156).
- core/skills/forge/references/artifacts.md, core/profile.default.json: republishing a page over 100 KB goes to a worker (I-322). codex.roles review and plan-review name gpt-6.1-sol, with plan-review at xhigh (I-410).
- aisetup/merge.py: a later layer's `sandbox.filesystem.denyRead` entries are added to earlier layers' entries instead of replacing them. An overlay can block a file without dropping core's `.env` patterns (I-433).
- aisetup/update.py: update recounts how far agent-kit is behind the required version after ai-setup moves, so one install.py update brings agent-kit up when the new ai-setup commit raises requires_agent_kit, instead of installing the new ai-setup on the old agent-kit until a second run.
- core/scripts/doctor.py: the installed-files path check skips tokens that contain `[` or `\`, so a regex quoted in a skill (ship-pr SKILL.md's changelog patterns) no longer fails every install with "referenced path does not exist".
- core/CLAUDE.md: before a code change outside forge, the main session asks once whether to draft a plan (recommended for more than 3 files or a behavior change), gives the change its own run dir, and always runs a code review after the change. Rapid-Fix uses that question as its confirmation.
- core/skills/forge (scripts/build-code-review-prompt.sh, references/code-review-prompt.md, scripts/build-plan-review-prompt.sh, references/codex-wrapper.md, references/forge-core.js): a code review prompt can be built for any change outside forge for Codex or Claude reviewers; plan review works without recon.md; forge runs pass their run dir to the new ship check.
- core/skills/ship-pr (SKILL.md, scripts/ship_record.py): the shipper checks for a plan answer and a current code review and returns NEEDS_SHIP_CONFIRM when either is missing; generic rules from ai-setup's copy (branch from origin/<base>, scoped restaging with at most 3 commit attempts, token-failure stop, gh 404 check, existing-PR body update, PR text in $TMPDIR files, edge cases) now live in core.
- core/agents/browser.md, modules/playwright/module.toml: the browser agent's Playwright MCP gets clipboard read and write permission, so QA can read back what a Copy button wrote instead of failing with NotAllowedError; the browser's clipboard stays separate from the host's.

## 2026-10-15
- core/skills/forge (scripts/gate.sh, references/gate-commands.md): a new optional gate key, `testFileInfixes`, makes a changed file run its same-name test file (`x.ts` runs `x.spec.ts`) for repos that keep tests next to the source.
- aisetup (compose.py), docs/overlay.md: gate entry keys may use `{{answers...}}` and `{{layers...}}` tokens, rendered at install and update. An empty answer drops the entry. Templates now get question defaults for answers missing from the profile.
- core/references/brief-template.md: restore the rule that a brief handing over a trace.zip, HAR or auth storage-state file forbids printing its raw contents; it was deleted along with the trace-read.py helper.
- core/skills/forge/scripts/gate.sh: a `--files` entry that is a `tests` folder now selects that folder for the test run; before, the folder path had no trailing slash, so the gate skipped tests and passed (inbox 2026-10-15T13:28).
- core/hooks/lint_check.py: lint only .py files with ruff and drop the eslint branch, which ran from the session cwd and returned "couldn't find an eslint.config" on 106 js/ts edits with no real finding (I-341); the forge gate still runs eslint.
- core/hooks/context_guard.py, core/settings.fragment.json, core/agents/claude-implementer.md: drop the Stop registration, which only reset state, and run the implementer PreToolUse limits from the claude-implementer frontmatter, so the main session no longer starts the hook on every tool call.
- modules/sandbox/settings.fragment.json: exclude `run_context.py smoke-run`, so the forge smoke run can read tracked env files that the Bash sandbox hides.
- core/CLAUDE.md: drop the "External contracts are captured" bullet (worker.md, build-lane.md and the forge plan rules keep it) and the step that messages an optimizing-workflow session after filing an inbox entry.
- core/scripts (handoff.py, drift_report.py, report_issue.py): handoff.py no longer lists user-log entries missing from STATE.md in the successor prompt (I-372, I-373); drift_report.py drops its unreflected-rate line; report_issue.py drops the unused ack, claim and list commands and files entries as before.
- CHANGELOG.md: the header says to cite an inbox id (I-xxx or C-xxx) when a change fixes an inbox entry.
- core/skills/precommit-hook-env-failure, core/skills/forge/scripts/trace-read.py, core/references/brief-template.md, core/settings.fragment.json: remove the unused precommit-hook-env-failure skill (0 Skill calls since 10-01), the trace-read.py helper and its brief-template line (2 runs since 10-01), and the security-guidance plugin entry (the Semgrep gate covers it).
- core/skills/forge (forge-core.js, SKILL.md, references): remove the `auto` launch argument and auto-mode.md (0 of 37 runs used it); the plan confirmation, the tests approval and the PRE_SHIP pause always apply, and the workflow_carry.py resume rule moves into SKILL.md step 6.
- core/skills/forge (SKILL.md, scripts/build-plan-review-prompt.sh, references): fold the triage.md investigation file into recon.md (4 of 37 runs used it); a narrow ask fills only the template's first three sections.

## 2026-10-14
- core/skills/forge/references/forge-core.js: the implementer sets `error` only when the work failed (notes go in summary or unverified), and runs Semgrep through the semgrep MCP because the local CLI cannot write its log under the Bash sandbox.
- core/scripts/git-net.sh, core/scripts/with-env.sh, core/scripts/handoff.py, core/skills/forge/scripts/codex-exec.sh, install.py: a call that runs inside the Bash sandbox stops with exit 86 and a message naming the bare call to use.
- core/skills/forge/scripts/gate.sh, core/skills/ship-pr/scripts/resolve-base-branch.sh, core/scripts/drift_report.py: a sandboxed run prints the bare-call message (gate.sh also adds it to its JSON warnings; the other two only on failure).
- core/skills/forge (references/forge-core.js, references/codex-wrapper.md): every forge prompt that names an excluded script says to run it as one bare call, and the Codex review prompt spells out the start and resume commands instead of a `$MODE` variable.
- core/skills/ship-pr/SKILL.md, modules/sandbox/CLAUDE.fragment.md: amend, push, fetch and pull lines say "one bare call", and the sandbox fragment names the stop message.
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
- core/CLAUDE.md, core/agents/browser.md: sub-agents wait on a done-file in the foreground instead of Monitor or a pgrep -f loop, and the browser agent types sign-in passwords instead of refusing.
- core/hooks/context_guard.py, modules/sandbox: run handoff.py and the other excluded scripts as one bare call, and commit through git-net.sh so pre-commit hooks can read tracked files the sandbox hides.
- core/skills/ship-pr, core/skills/forge/SKILL.md, core/scripts/handoff.py: the attribution check skips base-branch commits; staging skips already-staged deletions and stops on a failed add; commits go through git-net.sh; the base-branch resolver takes the repo path; the unread handoff marker is removed.
- core/skills/forge (forge-core.js, SKILL.md, references/auto-mode.md): a fix loop that stops for a human ruling first commits and pushes the fixes it applied when the branch is shipped, the loop is not blocked and the gate passes, and the needsJudge and final returns list the decision lines and any uncommitted paths.
- core/skills/forge/references/forge-core.js: the shipper skips `git add` for staged deletions that are still absent and stops before committing when a git add fails.
- core/skills/forge/scripts/gate.sh: a test command no longer gets a file or folder that sits inside another of its targets, so pytest collects the whole folder.
- core/skills/forge/references/forge-core.js: the implementer and commit gate prompts say to run gate.sh as one bare call, since a pipe or redirect keeps it in the Bash sandbox where tests cannot read env files.
- core/skills/forge/references/artifacts.md, core/skills/forge/scripts/render_artifact.py, core/skills/forge/references (templates): only forge's plan and QA pages render from templates; other artifacts are worker-written following the artifact-design skill, and the generic template and render mode are removed.

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
