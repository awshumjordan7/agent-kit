# Forge build lane

Use the default build lane for confirmed bugs, features, contract changes, and multi-phase work. The investigation may be a concise triage or a broader recon, but every build receives one plan review.

## What runs

| Step | Owner | Notes |
|---|---|---|
| Investigate | main session and scoped scouts | Diagnose before fixing: read the code path and capture live evidence before naming a cause. Map reusable patterns and affected callers. |
| Plan | main session | State the public contract, files, tests, acceptance criteria, access rules, risks, and run settings. |
| Plan review | configured reviewer | Build one prompt with the plan, investigation, excerpt pack, standards, and `plan-review-checks.md`; run one round and fold in critical findings. |
| Confirm | user | Skipped only in explicitly requested auto mode. |
| Workflow | `forge-core.js`, `args.lane='build'` | Implement, full gate, ship, optional QA, parallel Codex and Fable review plus lenses, triage, progress-based convergence, final gate, handoff. |

`quick-impl` is selected only when `fullySpecified` is true and the plan names no more source files than `quickReviewThreshold`; otherwise Forge uses `impl`. Tests and documentation do not count as source files.

## Evidence rules

- Put a `## Public API contract` in the plan for any client, CLI, library, data shape, or externally visible behavior. Implementation and verification must preserve it.
- When live behavior matters, build or keep a runnable evidence harness before feature work. Emit per-capability evidence with pass, fail, or blocked status.
- Verifiers read current code and evidence artifacts, never the fixer's summary. Codex reports inaccessible live targets as implemented-unverified.
- Maintain `STATUS.json` with acceptance criteria, evidence paths, round state, and open findings. Merge updates; never truncate prior evidence.
- When a deliverable mirrors a reference implementation, run both against the same target and compare observable results.
- Capture external contracts before confirmation. Build fixtures from captures, not guessed response shapes.

## Review panel

The Codex reviewer receives the validated diff file through `codex-exec.sh --inline-diff`. The Fable reviewer and path-selected lenses read that same file with the Read tool in ranges of at most 2,000 lines. Reviewers work independently and return file-and-line findings in the shared schema.

The triage agent confirms each finding against current code. Fix rounds run on fresh threads, are independently verified, and receive a tests-only gate. A final full gate controls whether fixes may be synchronized to an existing pull request.

## Multi-repository work

Use a separate run directory and repository-specific `planPath` for each repository. Start dependent work only when its required contract captures exist. Each repository has its own gate and ship decision; never make one repository's shipper poll another run's artifact.

## What the user receives

The handoff includes the implementation summary, gate result, review disposition, live-evidence status, manual QA checklist, decision log, branch and pull-request link, and optional sandbox metadata.
