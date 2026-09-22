---
name: forge
description: Turn a confirmed bug or feature plan into an implemented, repository-validated, independently reviewed pull request with optional QA stages.
---

# Forge

Forge has two lanes:

- `build` (default): investigate, plan, implement, run the repository's gate, pause at a pre-ship checkpoint, ship, optionally exercise a sandbox, review, apply at most one fix, and hand off.
- `review`: review and bounded fixes for existing changes. Pass a base ref when committed branch changes must be included.

`quick` and `dev` remain accepted aliases for `build` for one release. Add `auto` only when the user explicitly requested unattended execution.

## Procedure

1. Investigate before fixing: read the code path and capture live evidence before naming a cause. Write `triage.md` for a narrow, well-understood ask or `recon.md` when broader reuse and caller mapping are needed.
2. Write `plan.md` with a summary, public API contract, phases, exact files, acceptance criteria, risks, run settings, and one `## Tests` section. That section is the only place tests are defined: use one Markdown table with columns `Section`, `Test`, `Pins`, `How`, and `Why`, and one row per test. `Section` names the plan phase or component, `Test` names the file and test, `Pins` states the behavior proved in one sentence, `How` states setup, action, and assertion in one sentence, and `Why` names the risk or acceptance criterion protected. If the plan has no tests, write `## Tests` followed by the single line `None: <reason>`. Preserve evidence rules from `build-lane.md`.
3. Review every build plan once. Run `scripts/build-plan-review-prompt.sh`, which accepts either `recon.md` or `triage.md`, and write any extra file-and-line claims to `plan-review-checks.md`. Use `roles.plan-review` from `forge.config.json`: invoke `codex-exec.sh --role plan-review` for Codex or the configured Claude reviewer with the same prompt. Fold critical findings into the plan and record rejected findings with reasons.
4. Get explicit user confirmation of the plan unless `auto` was requested. In every mode, present the test table on its own, before or after the plan summary, and ask for an explicit yes on the tests as a separate answer from plan approval. For a no-tests plan, present `None: <reason>` in place of the table and get the same separate approval. A plan whose tests are not approved does not start; an `auto` run can proceed unattended only after that approval.
5. Load the rendered Forge config and start the Workflow. For multi-repository work, pass the repository-specific `planPath`. Set `fullySpecified=true` only when the caller supplied every material implementation choice; file count alone never makes work fully specified.

```text
Workflow({
  scriptPath: "~/.claude/skills/forge/references/forge-core.js",
  args: {
    lane, auto, runDir, projectDir, repo, ticket, criteria,
    planText, planPath, fullySpecified, stageAlso, ghEnvUnset,
    checkpointDecision, smokeCommand,
    forgeConfig: { roles, stages, thresholds, lenses, ticketUrl, repos, gate, ghEnvUnset }
  }
})
```

`planText` is required. When `forgeConfig` is absent, a small reader agent loads it; orchestration code never reads files directly.

6. When the Workflow returns `PRE_SHIP`, present the checkpoint summary and recommendation to the user with AskUserQuestion. Offer: ship as is; run the suggested smoke command, showing it as editable; or run a QA round. Relaunch the Workflow with the same args plus `checkpointDecision`, and include `smokeCommand` when smoke was selected.
7. Publish the handoff with gate and checkpoint evidence, review findings, unresolved work, decision records, and one manual QA item per acceptance criterion. Keep `decisions.md` append-only and rewrite `STATE.md` from the template. Preserve the Workflow id and session directory so `workflow_carry.py` can transfer it during a session handoff.

## Providers

Top-level `roles` selects provider, model, and effort:

- `impl` and `quick-impl`: implementation;
- `review`: final review and verification;
- `plan-review`: pre-implementation review.

Codex is the default implementation path. A role configured with `provider: claude` uses the `claude-implementer` agent. The Fable reviewer always runs beside the Codex reviewer, and matching lenses run in parallel. Codex budgets remain under `codex.roles`.

## Optional stages

Core ships optional stages disabled. An overlay may supply and enable:

- `stages.sandbox` → `references/stages/sandbox.md`
- `stages.ff_review` → `references/stages/ff_review.md`
- `stages.qa_login` → `references/stages/qa_login.md`
- ticket handling → `references/stages/ticket.md`

## Guardrails

- The user confirms the plan before implementation.
- The user separately approves the plan's test table, or its `None: <reason>`, before implementation.
- Gate behavior is repository-specific: `gate.mode` defaults to `full`; `none` spawns no gate agent and runs no tests, lint, typecheck, migrations, Semgrep, or parity commands. Personal repositories use `none` and have no tests.
- In `full` mode, the local gate must pass before shipping.
- Every build run pauses at a pre-ship checkpoint: a fresh reviewer summarizes the change and recommends ship, one smoke command, or a QA round. Attended runs ask the user; `auto` follows the recommendation, except a QA recommendation without a sandbox stage stops the run before shipping.
- Every review finding is triaged against current code before a fixer runs.
- Forge allows one fix round on a fresh implementation thread. One fresh Fable reviewer then verifies only the original post-triage findings from both reviewers using the implementer's per-finding explanations and the fix diff; it cannot add findings. Unresolved items go directly to the handoff, with no post-fix gate, status agent, judge, or second fix round.
- Review diffs are files. Codex receives the validated file through `--inline-diff`; Claude reviewers use the Read tool in ranges of at most 2,000 lines.
- Shippers stage exactly the changed-file context and never force-push without approval.
- Live-dependent capabilities remain implemented-unverified until a live harness proves them.
