# Forge build lane

Use the default build lane for confirmed bugs, features, contract changes, and multi-phase work. The investigation may be a concise triage or a broader recon, but every build receives one plan review.

## What runs

| Step | Owner | Notes |
|---|---|---|
| Investigate | main session and scoped scouts | Diagnose before fixing: read the code path and capture live evidence before naming a cause. Map reusable patterns and affected callers. |
| Plan | main session | State the public contract, files, acceptance criteria, access rules, risks, run settings, and one `## Tests` table with `Section`, `Test`, `Pins`, `How`, and `Why` columns; use `None: <reason>` when there are no tests. |
| Plan review | configured reviewer | Build one prompt with the plan, investigation, excerpt pack, standards, and `plan-review-checks.md`; run one round and fold in critical findings. |
| Confirm | user | Plan confirmation is skipped only in explicitly requested auto mode; separate test-table approval is never skipped. |
| Workflow | `forge-core.js`, `args.lane='build'` | Implement, repository-specific gate, pre-ship checkpoint, ship, optional QA, parallel Codex and Claude review plus lenses, triage, at most one fix with one scoped Claude verification, handoff. |

`quick-impl` is selected only when `fullySpecified` is true and the plan names no more source files than `quickReviewThreshold`; otherwise Forge uses `impl`. Tests and documentation do not count as source files.

## Phase loop

A plan with two or more `### Phase <id>: <title>` headings under `## Phases` runs one phase at a time:

1. Before the first phase, Forge switches to a new branch when the checkout is on the base branch, as ship-pr does, and records the run in `<runDir>/phases.json`.
2. Each phase gets its own implementer turn (`implement-phase-<id>`, `implementation-summary-phase-<id>.md`) with the full plan as context and the instruction to implement only that phase.
3. The phase's files are committed as `Phase <id>: <title>` through `gate.sh --no-stages --commit`, and the SHA is recorded in `<runDir>/phases.json`.
4. In gate mode `full`, the phase gate (`gate-phase-<id>`) runs on that SHA with `gate.sh --sha` in `<runDir>/gate-checkout` while the next phase is implemented. Gates run one at a time. The last phase gets no gate of its own: after every earlier gate and its fix commits have settled, the final gate runs on HEAD over every run file.
5. A failed gate is collected at the next phase boundary, never while an implementer is editing. The usual gate fix round runs in the primary worktree, each fix is committed as `Fix Phase <id> gate`, and that SHA is re-gated. The final gate, and any fix it needs, finishes before the pre-ship checkpoint.

Gate mode `none` keeps the phase commits, which still go through `gate.sh --no-stages`, and runs no gates. The review panel sees the whole branch diff once, and the shipper pushes the recorded branch and opens one PR after the checkpoint. A resumed run keeps `baseline.json` whenever `phases.json` exists, re-gates the pending and failed gates saved there, starts at the first uncommitted phase, and runs the final gate. The handoff removes the gate checkout; a run that stops for a judge or throws removes it directly.

Workflow resume args include `checkpointDecision` (`ship`, `smoke`, or `qa`) and optional `smokeCommand`. When a checkpoint returns `PRE_SHIP`, relaunch with the same args plus the user's decision; include the edited command for smoke.

## Evidence rules

- Put a `## Public API contract` in the plan for any client, CLI, library, data shape, or externally visible behavior. Implementation and verification must preserve it.
- When live behavior matters, build or keep a runnable evidence harness before feature work. Emit per-capability evidence with pass, fail, or blocked status.
- The post-fix verifier receives only the original post-triage findings, the implementer's per-finding explanations, and the fix diff. It marks each original finding `RESOLVED` or `UNRESOLVED`, cannot add findings, and sends unresolved items straight to handoff. Codex reports inaccessible live targets as implemented-unverified.
- Maintain `STATUS.json` with acceptance criteria, evidence paths, round state, and open findings. Merge updates; never truncate prior evidence.
- When a deliverable mirrors a reference implementation, run both against the same target and compare observable results.
- Capture external contracts before confirmation. Build fixtures from captures, not guessed response shapes.

## Review panel

The Codex reviewer receives the validated diff file through `codex-exec.sh --inline-diff`. The Claude reviewer and path-selected lenses read that same file with the Read tool in ranges of at most 2,000 lines. Reviewers work independently and return file-and-line findings in the shared schema.

The triage agent confirms each finding against current code. Forge runs at most one fix round on a fresh thread, followed by one fresh Claude reviewer scoped to the original findings. There is no post-fix gate, status agent, verification judge, or repeat fix round.

## Repository gate modes

`gate.mode` is resolved per repository and defaults to `full`. Full mode retains the configured gate. Personal repositories use `none`: they have no tests, spawn no gate agent, and run no test, lint, typecheck, migration, Semgrep, or parity command; Forge still creates the review diff with plain `git diff`.

Every build pauses after the gate at a pre-ship checkpoint. A fresh reviewer summarizes the change and recommends shipping, one smoke command, or a QA round. Attended runs ask the user; `auto` follows the recommendation, except a QA recommendation without an enabled sandbox stops before shipping. Mode `none` still reaches this checkpoint after skipping its gate.

## Multi-repository work

Use a separate run directory and repository-specific `planPath` for each repository. Start the dependent repository's run as soon as the upstream phase commit and its captures exist, not when the upstream run ends. Each repository has its own gate mode and ship decision; never make one repository's shipper poll another run's artifact.

## What the user receives

The handoff includes the implementation summary, gate and checkpoint result, review disposition, live-evidence status, manual QA checklist, decision log, branch and pull-request link, and optional sandbox metadata. For `mode: none`, it states `gates: none (personal repo)` and cites `checkpoint.json`.
