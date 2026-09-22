# Codex cost controls

Why every Codex session forge runs is bounded, what the bounds are, and where they live.
The rules are enforced in `scripts/codex-exec.sh` and configured in `forge.config.json`;
this file explains them so nobody re-derives (or relaxes) them by accident.

## The rule

A Codex session gets its inputs inline and a numeric budget. It reads the repository only to
confirm a named `file:line`, with ranged reads. It never gets "read these files in full".
Stall timeout is 300 s (`stallTimeoutSeconds`). `watch` always runs in the background so a stall
surfaces as a notification, never as a silent hang.

- `references/codex-prompt-contract.md` is prepended to every prompt by `codex-exec.sh`
  (section per role: `review` for plan review, code review, verify; `impl` for implementation
  and first-round fixes). The role's budget numbers are filled in.
- `forge.config.json` per role: `maxToolCalls`, `maxToolOutputKB` (the harness kills the session
  past either), `toolOutputTokenLimit` (Codex's own per-call truncation), `webSearch: disabled`,
  `mcp` (normally false for reviewers and configurable for implementers), and
  `contract`.
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
  and appends a line to `.state/usage.log`. `codex-exec.sh stats --log <events.jsonl>` and
  `scripts/codex-log-stats.py <events.jsonl>` report the same for any log after the fact.

## Local gate role
`gate` role (runs `scripts/gate.sh`): Haiku, low effort, 3-7 spawns per run; cost is test wall-clock time, not tokens.

## Review roles back on Sol (2026-09-16)
`roles.review` and `roles.plan-review` moved from gpt-6-astra to gpt-5.6-sol at high effort. One astra plan review used about 20% of the 5-hour limit; astra is priced roughly 50x the 5.6 models. Revisit only if Sol review quality is not enough.

## Sol implementer trial (from 2026-09-15)

`roles.impl` moved from gpt-5.6-luna to gpt-5.6-sol at high effort. Luna baseline from
`.state/usage.log` (2026-09-10 billing-visibility run): implement sessions 81 to 108 tool calls,
340 to 999 KB tool output, fix rounds up to 5, one `budget_exceeded`. Record the first three Sol
`CODEX_OK` lines here and decide: fewer fix rounds and tool calls at acceptable cost keeps Sol;
otherwise revert the one config line. Sol pricing: not recorded in the local model cache; check
the Codex dashboard before comparing dollars.

2026-09-15 forge-core.js edit (7 spec items, excerpts inline): CODEX_OK role=impl model=gpt-5.6-sol effort=high tool_calls=31 tool_output_kb=80 tokens_in=955829 tokens_cached=876160 tokens_out=13298 tokens_reasoning=5534. All items done in one pass, node --check clean, no fix round.
2026-09-15 forge-core.js smoke edit (3 spec items, excerpts inline): CODEX_OK role=impl model=gpt-5.6-sol effort=high tool_calls=3 tool_output_kb=25 tokens_in=103700 tokens_cached=77184 tokens_out=3483 tokens_reasoning=1665. All items done in one pass, node --check clean, dry run DONE.
2026-09-16 forge-core.js PR body, sandbox marker, smoke sign-in (3 spec items, excerpts inline): CODEX_OK role=impl model=gpt-5.6-sol effort=high tool_calls=1 tool_output_kb=0 tokens_in=69413 tokens_cached=59648 tokens_out=1125 tokens_reasoning=500. All items done in one pass, node --check clean. Third Sol line: all three forge-core edits landed first pass with 1 to 33 tool calls; Sol stays as impl.

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

With inputs inline and the `review` budget (30 calls, 200 KB), a plan review or code review on
the flagship at high effort is a few dollars, mostly cached input. The implementer stays on the
cheap model. Compare each run's `CODEX_OK` line against these before starting the next repo of
a multi-repo feature.

The Fable general reviewer runs in parallel with the Codex reviewer and reads the diff file in
bounded ranges. Reference pricing at the time of writing (per 1M tokens, input / cached /
output): gpt-6-astra 10 / 1 / 50; gpt-5.6-luna 0.20 / 0.02 / 1.20; requests above 272K input
tokens bill at 2x input.

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
  at the time and each sub-agent is another billed session. Not adopted; Sonnet scouts and the
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

## quick-impl on Luna (from 2026-09-20)

`roles.quick-impl` uses gpt-5.6-luna at high effort. Build-lane changes are fully specified
edits whose plan names at most `quickReviewThreshold` source files (default 8). Otherwise Forge uses `impl`.
Tests, Markdown, and JSON files do not count toward that threshold, so the exploration that made Luna expensive
before 2026-09-15 no longer applies.

Prices per 1M tokens (input / cached / output): Luna 0.20 / 0.02 / 1.20; Terra 2.00 / 0.20 /
12.00; Sol 4.00 / 0.40 / 20.00.

Measure five quick runs. For each run, record the `CODEX_OK` line, fix-round count, and whether
the gate failed. The per-run revert condition is more than one fix round on a fully specified
change, or a `failed` / `budget_exceeded` outcome. On failure, move `quick-impl` to
gpt-5.6-terra for the next five runs. If Terra also fails, move it back to gpt-5.6-sol. Review
and plan-review stay on Sol throughout.

| Run | Date | CODEX_OK summary | Fix rounds | Gate |
|---|---|---|---|---|
| 1 |  |  |  |  |
| 2 |  |  |  |  |
| 3 |  |  |  |  |
| 4 |  |  |  |  |
| 5 |  |  |  |  |
