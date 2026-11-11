# Forge build lane

Use the default build lane for confirmed bugs, features, contract changes, and multi-phase work. The investigation is `recon.md`, short for a narrow ask and broader when reuse and caller mapping matter, and every build receives one plan review.

## What runs

| Step | Owner | Notes |
|---|---|---|
| Investigate | main session and scoped scouts | Diagnose before fixing: read the code path and capture live evidence before naming a cause. Map reusable patterns and affected callers. |
| Plan | main session | State the public contract, files, acceptance criteria, access rules, risks, run settings, and one `## Tests` table with `Section`, `Test`, `Pins`, `How`, and `Why` columns; use `None: <reason>` when there are no tests. A plan that changes instruction files carries `## Changelog`, and its last phase writes those lines to CHANGELOG.md. |
| Plan review | configured reviewer | Build one prompt with the plan, investigation, excerpt pack, standards, and `plan-review-checks.md`; run one round and fold in critical findings. |
| Confirm | user | The user confirms the plan, test table included, before the run starts. On approval of a plan with `## Changelog`, the main session writes `<runDir>/user-ok.md` with the quoted approval and date; ship-pr's changelog check needs it. |
| Workflow | `forge-core.js`, `args.lane='build'` | Implement, repository-specific gate, ship, parallel Codex and Claude review plus lenses, triage, the capped fix loop (at most `MAX_FIX_ROUNDS` (2) rounds, each gate-failure round re-running the full gate and each review-fix round running lint, typecheck and Semgrep when a gate is configured and, when review items changed, re-checked by a scoped Claude verifier; one full gate runs on the final state when review fixes were applied, and a failing final gate runs up to 2 more fix rounds with a full gate each), handoff. |

The `implementer` agent writes the code at its file's model and effort, whether or not `fullySpecified` is true.

## Phase loop

A plan with two or more `### Phase <id>: <title>` headings under `## Phases` runs one phase at a time:

1. Before the first phase, Forge switches to a new branch when the checkout is on the base branch or detached, as ship-pr does. A launch with `continueBranch` stays on that branch. Forge records the run in `<runDir>/phases.json`, which `run_context.py phases-save` writes with titles taken from the plan file. A failed write stops the run BLOCKED.
2. Each phase gets its own implementer turn (`implement-phase-<id>`) with the full plan as context and the instruction to implement only that phase.
3. The phase's files are committed as `Phase <id>: <title>` through `gate.sh --no-stages --commit`, and the SHA is recorded in `<runDir>/phases.json`.
4. In gate mode `full`, the phase gate (`gate-phase-<id>`) runs on that SHA with `gate.sh --sha` in `<runDir>/gate-checkout` while the next phase is implemented. Gates run one at a time. The last phase gets no gate of its own: after every earlier gate and its fix commits have settled, the final gate runs on HEAD over every run file.
5. A failed gate is collected at the next phase boundary, never while an implementer is editing. The fix loop runs in the primary worktree, each applied round is committed as `Fix Phase <id> gate`, and that SHA is re-gated. The final gate, and any fix it needs, finishes before ship.

Gate mode `none` keeps the phase commits, which still go through `gate.sh --no-stages`, and runs no gates. The review panel sees the whole branch diff once, and the shipper pushes the recorded branch and opens one PR after the final phase. Every diff starts at the merge-base with the base branch. A resumed run re-gates the pending and failed gates saved in `phases.json`, starts at the first uncommitted phase, and runs the final gate. The handoff removes the gate checkout; a run that stops for a judge or throws removes it directly.

A new session passes `resumeFromRunId` only after carrying the journal over with `workflow_carry.py` (see `SKILL.md` step 6).

## Evidence rules

- Put a `## Public API contract` in the plan for any client, CLI, library, data shape, or externally visible behavior. Implementation and verification must preserve it.
- When live behavior matters, build or keep a runnable evidence harness before feature work. Emit per-capability evidence with pass, fail, or blocked status.
- Harness and QA setup must be idempotent: use get_or_create/update_or_create, or clean up the rows it owns first, so the setup is safe to run twice against the same database.
- The post-fix verifier receives only the original post-triage findings, the implementer's per-finding explanations, and the fix diff. It marks each of those findings `RESOLVED` or `UNRESOLVED` and cannot add findings; unresolved items stay open for the next round or the BLOCKED handoff. Codex reports inaccessible live targets as implemented-unverified.
- When a deliverable mirrors a reference implementation, run both against the same target and compare observable results.
- Capture external contracts before confirmation. Build fixtures from captures, not guessed response shapes.

## Review panel

The Codex reviewer receives the validated diff file through `codex-exec.sh --inline-diff`. The Claude reviewer and path-selected lenses read that same file with the Read tool in ranges of at most 2,000 lines. Reviewers work independently and return file-and-line findings in the shared schema. When every changed file is docs, instruction text or config and none is an instruction file, the Codex reviewer is skipped and decisions.md records the skip; the Claude reviewer and triage always run.

The triage agent confirms each finding against current code. Confirmed findings, and gate failures, go through the capped fix loop: at most `MAX_FIX_ROUNDS` (2) rounds of decide, apply, then check. The `judge` agent decides the fix spec and applies a small fix set itself; otherwise the `implementer` agent applies only that spec. In gate mode `full`, gate-failure rounds re-run the full gate, and review-fix rounds run lint, typecheck and Semgrep only. When review fixes were applied, one full gate (`gate-fix-final`) runs on the final state; a failing final gate runs up to 2 more fix rounds with a full gate each. A fresh Claude reviewer re-checks only the review items fixed that round. The loop returns BLOCKED `fix-cap` at the cap and BLOCKED `no-progress` when a round shrinks neither the open review set nor the failing gate count. Rejected, deferred, and cannot-decide review items stop the run for a human ruling. Before that stop, forge commits and pushes the fixes it applied when the run has a shipped branch, the loop is not blocked and the gate passes.

## Repository gate modes

`gate.mode` is resolved per repository and defaults to `full`. Full mode retains the configured gate. Personal repositories use `none`: they have no tests, spawn no gate agent, and run no test, lint, typecheck, migration, or Semgrep command; Forge still creates the review diff with plain `git diff`.

Every build goes from the gate straight to ship, with no pause. QA runs only by hand, on demand, with the overlay stage docs. Mode `none` goes straight to ship after skipping its gate.

## Multi-repository work

Use a separate run directory and repository-specific `planPath` for each repository. Start the dependent repository's run as soon as the upstream phase commit and its captures exist, not when the upstream run ends. Each repository has its own gate mode and ship decision; never make one repository's shipper poll another run's artifact.

## What the user receives

The handoff includes the implementation summary, gate result, review disposition, live-evidence status, manual QA checklist, decision log, and branch and pull-request link. For `mode: none`, it states `gates: none (personal repo)`.
