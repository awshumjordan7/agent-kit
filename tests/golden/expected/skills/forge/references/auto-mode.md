# forge … auto — unattended runs

`forge quick auto`, `forge dev auto`, or `forge auto` after an investigation.
Same lane, no stops. The user is away; the run makes its best call and leaves a trail.

## What is skipped

- The plan confirm. The plan artifact is still published, for the record.
- Clarifying questions. Pick the reading closest to the ticket/spec text; log it.
- Waiting on the user for the judge. The finding is applied (conservative default); log it.
- Ticket approval. One ticket at most per run, and only after the JQL search finds nothing.

## What is never skipped

- The local gate and the sandbox gate.
- Lane limits. A quick run that turns out big **stops** with the triage and one line of
  reason. It never widens itself into a dev run.
- The two-round fix cap. A third failure stops the run as `READY_FOR_HUMAN`, ships nothing else,
  and writes the failure list and resume pointers to `STATE.md`.
- Bot-review triage stops for the user. Auto never addresses bot findings by itself.

## The trail — `decisions.md`

Every judgment call is appended as it happens (crash-safe), one line each:

    [step] decision — reason

Sources: interpretation choices, judge rulings, Opus fallbacks (a Fable role returned
nothing and was retried on Opus), skipped stages (sandbox MCP unavailable, lens returned
null), lane-limit stops. The handoff artifact renders this as **Judgment calls**.
Access-rule sentences are also written here and in the plan artifact before the run continues.

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
- Resume is same-session only. A successor session must first copy `<oldSession>/workflows/<runId>.json` and `<oldSession>/subagents/workflows/<runId>/` from `~/.claude/projects/<project>/` into its own session directory. A cached agent result whose `error` is non-empty replays as a failure; delete its `started` and `result` lines from `journal.jsonl` (back the file up first) so only that agent re-runs.

## How it ends

PR open, handoff artifact published, optional review stages complete, and then it waits.
