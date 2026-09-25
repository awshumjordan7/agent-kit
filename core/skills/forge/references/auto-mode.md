# forge … auto — unattended runs

`forge build auto` or `forge auto` after an investigation.
Same lane, no stops. The user is away; the run makes its best call and leaves a trail.

## What is skipped

- The plan confirm after the tests have been separately approved. The plan artifact is still rendered and published (SKILL.md step 4), for the record.
- Clarifying questions. Pick the reading closest to the ticket/spec text; log it.
- Waiting on the user for review-panel contradictions and uncertain triage verdicts. The finding is applied (conservative default); log it. Fix-loop items the decider rejects, defers, or cannot decide are not skipped: they stop auto runs too (see below).
- Ticket approval. One ticket at most per run, and only after the JQL search finds nothing.

## What is never skipped

- Test-table approval. Auto starts only after the user explicitly approves the table or its `None: <reason>`.
- The local gate and the sandbox gate.
- Scope limits. A run that needs a materially different plan stops with the evidence and reason.
- The capped fix loop. It stops BLOCKED at `MAX_FIX_ROUNDS` (2) rounds, or earlier when a round shrinks neither the open review set nor the failing gate count, with the open items and decider notes in the handoff. Review items the decider rejects, defers, or cannot decide still stop for a human ruling.
- Bot-review triage stops for the user. Auto never addresses bot findings by itself.

## The trail — `decisions.md`

Every judgment call is appended as it happens (crash-safe), one line each:

    [step] decision — reason

Sources: interpretation choices, judge rulings, Opus fallbacks (a Fable role returned
nothing and was retried on Opus), skipped stages (sandbox MCP unavailable, lens returned
null), lane-limit stops. The handoff artifact renders this as **Judgment calls**.
Access-rule sentences are also written here and to `accessRules` in `plan-data.json`, and the plan artifact is re-rendered (SKILL.md step 4) before the run continues.

## The state — `STATUS.json`

Alongside the prose trail, the run dir carries `STATUS.json` (criteria → status/evidence/round,
rounds, open findings). forge-core merges into it at smoke, each fix round, and handoff — it is
never truncated, so it survives a crashed or killed run. A resume (`resumeFromRunId`) or a fresh
session picks up from its weakest entry rather than from scratch; the handoff renders from it.
`decisions.md` is append-only for the same reason.

## Reliability guards

- Spawn cap (`args.spawnCap`, default 32 agent spawns). Exceeded → `BLOCKED` with a decision line.
- Per-agent timeouts bound wall-clock; the Workflow runtime has no clock of its own.
- Isolated failures: a lens or smoke agent that dies becomes a `FAIL` row in the handoff, not an aborted run.
- Workflow resume: re-running after a crash skips completed stages.
- A successor session runs `workflow_carry.py <runId> --from <old-session-dir> --to <new-session-dir>` before resuming. A cached agent result whose `error` is non-empty replays as a failure. For a Codex stage, relaunch with `resumeFromRunId` and `resumeAttempt` raised by one; each Codex stage whose cached result still carries an error gets one fresh attempt, and every call after it runs live. For any other agent, remove only that failed entry after preserving the journal.

## How it ends

PR open, handoff artifact published, optional review stages complete, and then it waits.
