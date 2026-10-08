# Codex cost controls

Why every Codex session forge runs is bounded, what the bounds are, and where they live.
The rules are enforced in `scripts/codex-exec.sh` and configured in `forge.config.json`;
this file explains them so nobody re-derives (or relaxes) them by accident.

## The rule

A Codex session gets its inputs inline and a numeric budget. It reads the repository only to
confirm a named `file:line`, with ranged reads. It never gets "read these files in full".
Stall timeout is 300 s (`stallTimeoutSeconds`), the same for the run and `watch`. A session counts
as stalled only when neither its event log nor its Codex rollout file (which grows with reasoning)
changed for that long. Each `watch` call restarts the idle count, so its own stall exit (75) needs
`--max-wait` above the stall timeout (`CODEX_STARTED` prints `--max-wait 2400`); the run's
watchdog, which kills a stalled session and writes `<log>.failed`, is the primary stall detector.
`watch` always runs in the background so a stall surfaces as a notification,
never as a silent hang.

- `references/codex-prompt-contract.md` is prepended to every prompt by `codex-exec.sh`
  (one `review` section for plan review, code review, verify).
  The role's budget numbers are filled in.
- `forge.config.json` per role: `maxToolCalls`, `maxToolOutputKB` (the harness kills the session
  past either), `toolOutputTokenLimit` (Codex's own per-call truncation), `webSearch: disabled`,
  `mcp` (normally false), and `contract`.
- Plan review prompts inline the plan, recon, code standards, and an excerpt pack cut from every
  `file:line` the recon cites (capped, default 60 KB). The main session adds numbered checks, each
  a claim with a `file:line`. The configured reviewer verifies; it does not explore.
- Code review writes the uncapped diff to the run directory. `codex-exec.sh --inline-diff`
  validates and inlines up to 160,000 characters for Codex; Claude reviewers read the file in
  ranges of at most 2,000 lines.
- Sessions run one at a time (`.state/session.lock`); `--parallel` only when the user asks.
- The "out of credits" error kills that session at once with `CODEX_NO_CREDITS`; after billing
  is fixed, a later start can retry normally.
- Every run prints `CODEX_OK … tool_calls= tool_output_kb= tokens_in= tokens_cached= tokens_out=`
  and appends a line to `.state/usage.log`. `codex-exec.sh stats --log <events.jsonl>`
  reports the same for any log after the fact.

## Local gate role
`gate` role (runs `scripts/gate.sh`): Haiku, low effort, 3-7 spawns per run; cost is test wall-clock time, not tokens.

## Routing (2026-09-22)
`roles.impl` runs on Claude Opus 5.5 at high effort, `roles.quick-impl` (small, fully specified work and most fix rounds) at medium, and `roles.plan-review` at xhigh. The Claude reviewer and pre-ship checkpoint run at xhigh; triage and the fix decider (`judge` agent) at high. The fix applier uses `roles.quick-impl`. Each fix loop raises the spawn cap by 3 per round (decider, applier, gate or verify), plus 1 per round for the phase commit in phased runs. The final full gate after applied review fixes adds 1 spawn, and its own fix loop, when that gate fails, adds the per-round budget again. `roles.review` runs on Codex gpt-6-sol at xhigh effort, the only Codex use. It replaced gpt-6-astra on 2026-09-22 because one astra review could use about 20% of the 5-hour limit. Watch per-review usage in `.state/usage.log`.

## Why (retro, 2026-09-10)

Three dev-lane plan reviews for the billing-visibility feature ran in parallel on the flagship
review model at high effort. Each prompt told Codex to "read these files in full" for about
20 files, several of them thousands of lines, then "verify the plan against the actual code".
All three died with "Your workspace is out of credits", twice, before and after a refill.

| Run | Shell commands | Whole-file dumps | Tool output | Ended |
|---|---|---|---|---|
| service A | 34 | 28 | 429 KB | out of credits |
| service B | 44 (+2 web searches, +1 MCP call) | 30 | 500 KB | out of credits |
| web app | 82 | 44 | 417 KB | out of credits |

Every tool result stays in the model context and is re-sent on every following model call, so
80 calls over a context growing toward 130K tokens is millions of input tokens per review at
flagship rates. The model choice was not the driver; the exploration was. Other contributors:
Codex auto-loads `AGENTS.md`, so the prompt's "read AGENTS.md"
read it twice; web search defaults to on and every MCP server was reachable; three flagship
sessions ran at once, so one credit failure cost three sessions. The same pool had been
drained on 2026-08-31 by running xhigh effort everywhere (impl dropped to high 2026-09-01;
review moved to the astra model 2026-09-04).

## Expected cost

With inputs inline and the Codex `review` budget (`maxToolCalls` 150, `maxToolOutputKB` 300),
a code review on gpt-6-sol at xhigh effort is mostly cached input. Compare each run's
`CODEX_OK` line against these before starting the next repo of a multi-repo feature.

The Claude general reviewer runs in parallel with the Codex reviewer and reads the diff file in
bounded ranges. gpt-6-sol pricing is not recorded in the local model cache; check the Codex
dashboard before comparing dollars.

## What the Codex CLI gives us (0.154.0)

- `codex exec --json` events: `thread.started`, `turn.started`, `item.started/completed`,
  `turn.completed` (with `usage`: input, cached input, output, reasoning tokens; cumulative per
  thread in exec mode), `error`, `turn.failed`. No CLI flag caps turns, tokens, tool output, or
  wall time; the harness does it from the event log.
  https://learn.chatgpt.com/docs/non-interactive-mode https://github.com/openai/codex/issues/17539
- Config overrides used per session: `tool_output_token_limit`, `web_search=disabled`,
  `mcp_servers.<id>.enabled=false`. `project_doc_max_bytes` governs AGENTS.md loading (default
  32 KiB; adjust only when a repository needs it).
  https://learn.chatgpt.com/docs/config-file/config-reference
  https://learn.chatgpt.com/docs/agent-configuration/agents-md
- OpenAI's prompting guidance for this model family: lower exploration with an explicit
  context-gathering budget ("search depth: very low", a maximum tool-call count, stop once you
  can name the exact change) and reasoning effort as the lever for "how willingly it calls
  tools". Their own review product "operates on diff-only reads rather than full repository
  access". https://developers.openai.com/cookbook/examples/gpt-5/gpt-5_prompting_guide
  https://learn.chatgpt.com/docs/code-review?surface=app
- Sub-agents exist (`multi_agent`, `agents.default_subagent_model`, per-spawn model) and could
  push reading onto a cheaper model, but a regression on per-subagent model selection was open
  at the time and each sub-agent is another billed session. Not adopted; `scout` agents and the
  excerpt pack do the reading on the Claude side.
  https://learn.chatgpt.com/docs/agent-configuration/subagents
- The out-of-credits error text: "Your workspace is out of credits. Ask your workspace owner
  to refill in order to continue." The CLI can hang on it, hence the kill.
  https://github.com/openai/codex/issues/27598 https://github.com/openai/codex/issues/6512

## Follow-ups

- Measure the first bounded plan review (the paused billing-visibility run) and record its
  `CODEX_OK` line here as the baseline.
- Evaluate `codex review` (top-level, diff-only, non-interactive) as the code-review mechanism
  once it can take the checklist and plan summary.
- Re-test Codex sub-agents on a cheaper model when the model-selection regression is closed.
