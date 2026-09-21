---
name: forge
description: Turn a confirmed bug or feature plan into an implemented, gated, reviewed pull request with an optional QA stage.
---

# Forge

Forge has four lanes:

- `quick`: confirmed fixes of at most three files, with no migration or architecture change.
- `dev`: multi-file or multi-phase work from a confirmed plan.
- `review`: review and bounded fixes for existing changes.
- `implement`: implement an existing phased plan without shipping.

Add `auto` only when the user requested unattended execution.

## Workflow

1. Investigate with scoped scouts. Write `triage.md` for quick work or `recon.md` for dev work.
2. Write `plan.md` with a summary, public contracts, phases, tests, acceptance criteria, and checkpoints.
3. Review the plan once in dev. Read `roles["plan-review"].provider` from `forge.config.json`:
   - `codex`: run `codex-exec.sh --role plan-review` with the built prompt.
   - `claude`: spawn a `reviewer` with the same prompt and configured model and effort.
4. Get explicit user confirmation unless `auto` was requested.
5. Read `roles` and `stages` from `forge.config.json`, then pass them to the Workflow:

```text
Workflow({
  scriptPath: "~/.claude/skills/forge/references/forge-core.js",
  args: {
    lane, auto, runDir, projectDir, repo, ticket, criteria,
    planText, planPath,
    forgeConfig: { roles, stages }
  }
})
```

When `forgeConfig` is absent, Forge uses a Haiku read agent to load the same file. The Workflow itself never reads files directly.

6. Publish the handoff with gate results, review findings, unresolved work, and manual QA items.

## Providers

The top-level `roles` block controls provider, model, and effort:

- `impl` and `quick-impl`: implementation and their fix rounds.
- `review`: final review and fix verification.
- `plan-review`: the pre-implementation plan review.
- `spot-review`: checkpoint review.
- `qa`: QA drafts and smoke work.

When an implementation role uses `claude`, Forge calls the `implementer` agent. When it uses `codex`, Forge calls `codex-exec.sh`. A Codex review runs beside the Claude reviewer in the dev lane. A Claude review skips the Codex reviewer.

Budgets remain under `codex.roles`; `codex-exec.sh` resolves model and effort from top-level `roles` first and falls back to `codex.roles`.

## Optional stages

Core ships all optional stages off. When an overlay enables a stage, follow its matching reference:

- `stages.sandbox` → `references/stages/sandbox.md`
- `stages.ff_review` → `references/stages/ff_review.md`
- `stages.qa_login` → `references/stages/qa_login.md`

Core does not ship those stage references.

## Guardrails

- The user confirms the plan before implementation.
- Every implementation segment has a local gate and checkpoint review.
- Fixes are capped at two rounds. A third failure stops for human review.
- Codex prompts carry bounded inline context and use the configured tool budgets.
- The main session never writes code, runs test suites, commits, or pushes.
- Shipper stages explicit paths only and never force-pushes without approval.
- Live-dependent capabilities remain implemented-unverified until a live harness proves them.
- `decisions.md` is append-only. `STATE.md` is rewritten for handoff.
