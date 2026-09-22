# Forge build lane

Use the default build lane for confirmed bugs, features, contract changes, and multi-phase work. The investigation may be a concise triage or a broader recon, but every build receives one plan review.

## What runs

| Step | Owner | Notes |
|---|---|---|
| Investigate | main session and scoped scouts | Diagnose before fixing: read the code path and capture live evidence before naming a cause. Map reusable patterns and affected callers. |
| Plan | main session | State the public contract, files, tests, acceptance criteria, access rules, risks, and run settings. |
| Plan review | configured reviewer | Build one prompt with the plan, investigation, excerpt pack, standards, and `plan-review-checks.md`; run one round and fold in critical findings. |
| Confirm | user | Skipped only in explicitly requested auto mode. |
| Workflow | `forge-core.js`, `args.lane='build'` | Implement, repository-specific gate or real run, ship, optional QA, parallel Codex and Fable review plus lenses, triage, at most one fix with one scoped Fable verification, handoff. |

`quick-impl` is selected only when `fullySpecified` is true and the plan names no more source files than `quickReviewThreshold`; otherwise Forge uses `impl`. Tests and documentation do not count as source files.

## Evidence rules

- Put a `## Public API contract` in the plan for any client, CLI, library, data shape, or externally visible behavior. Implementation and verification must preserve it.
- When live behavior matters, build or keep a runnable evidence harness before feature work. Emit per-capability evidence with pass, fail, or blocked status.
- The post-fix verifier receives only the original post-triage findings, the implementer's per-finding explanations, and the fix diff. It marks each original finding `RESOLVED` or `UNRESOLVED`, cannot add findings, and sends unresolved items straight to handoff. Codex reports inaccessible live targets as implemented-unverified.
- Maintain `STATUS.json` with acceptance criteria, evidence paths, round state, and open findings. Merge updates; never truncate prior evidence.
- When a deliverable mirrors a reference implementation, run both against the same target and compare observable results.
- Capture external contracts before confirmation. Build fixtures from captures, not guessed response shapes.

## Review panel

The Codex reviewer receives the validated diff file through `codex-exec.sh --inline-diff`. The Fable reviewer and path-selected lenses read that same file with the Read tool in ranges of at most 2,000 lines. Reviewers work independently and return file-and-line findings in the shared schema.

The triage agent confirms each finding against current code. Forge runs at most one fix round on a fresh thread, followed by one fresh Fable reviewer scoped to the original findings. There is no post-fix gate, status agent, verification judge, or repeat fix round.

## Repository gate modes

`gate.mode` is resolved per repository and defaults to `full`. Full mode retains the configured gate. Personal repositories use `none`: they have no tests, spawn no gate agent, and run no test, lint, typecheck, migration, Semgrep, or parity command; Forge still creates the review diff with plain `git diff`.

Mode `none` runs `gate.realRun` once after implementation with a 900-second cap. A plan may override the command with `real_run` under `## Run Settings`. A non-zero exit blocks and is recorded in `realrun.log`; absence of a configured command is non-blocking but must appear as `real run: not configured` at the start of the handoff.

## Multi-repository work

Use a separate run directory and repository-specific `planPath` for each repository. Start dependent work only when its required contract captures exist. Each repository has its own gate mode and ship decision; never make one repository's shipper poll another run's artifact.

## What the user receives

The handoff includes the implementation summary, gate or real-run result, review disposition, live-evidence status, manual QA checklist, decision log, branch and pull-request link, and optional sandbox metadata. For `mode: none`, it states `gates: none (personal repo)` and cites `realrun.log` when a real run was configured.
