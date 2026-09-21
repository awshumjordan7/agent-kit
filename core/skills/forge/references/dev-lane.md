# forge dev — the feature lane

For multi-file, multi-phase work. Input is a spec — usually `spec.md` from the
`brainstorming` skill — or an existing `plan.md`.

## What runs

| Step | Who | Notes |
|---|---|---|
| Recon → `recon.md` | main session + Sonnet scouts | what exists to reuse, callers of everything being touched, patterns to copy, constraints. `cgc update` then `cgc analyze callers|calls|overrides` when indexed |
| Plan → `plan.md` + plan artifact | main session | phases, files per phase, test strategy, acceptance criteria, `sandbox_tier`, expected lenses, checkpoints at dependency boundaries (`## Checkpoints`). For every access rule, state who, the permission atom, the target tenant, and the status in one sentence; get an explicit yes and store it in `accessRules[]`. Plain English in the artifact |
| Plan review | configured reviewer | **one round** with the `plan-review` role from `forge.config.json`. Build one prompt file containing the plan, recon, excerpt pack, and the main session's `file:line` checks. Use `codex-exec.sh --role plan-review` when the provider is Codex; otherwise spawn a `reviewer` agent with the configured model and the same prompt. One round; CRITICAL findings are folded in and restated to the user. Fold findings into the plan; note what was rejected and why. Multi-repo: one repo at a time |
| Confirm | user | skipped in `auto` |
| Workflow | `forge-core.js`, `args.lane='dev'` | plan with no `## Checkpoints`: implement → gate (`scripts/gate.sh` run by a Haiku `gate` agent: lint, typecheck, migrations, targeted tests, Semgrep; JSON also written to `<runDir>/gate-<label>.json`; checkpoint diffs to `gate-<label>.diff`; an optional per-repo `parity` list in the gate config runs extra commands that mirror CI (pinned linter version, foreign HOME, missing optional binaries, workflow lint); agent-kit uses `tests/ci_parity.sh`) → ship → sandbox + smoke → **review panel** → judge if needed → up to two Codex fix rounds with verification → handoff. Each checkpoint segment starts a fresh Codex implementation thread; gate and spot fixes resume that segment's thread. Final review fixes use their own `codex-fix.thread`. Pass `planText` in args, else one `read-plan` Sonnet agent reads it; `planPath` selects the plan file per repo (default plan.md) |
| Bot triage | main session | When `stages.ff_review` is on, follow `references/stages/ff_review.md` |

## The review panel

Runs once, in parallel:
- **Configured reviewer** — Codex or Claude from `roles.review`. Gets the diff inline (capped at 160k characters, told when cut),
  the plan summary, criteria, checklist, and standards; `codex-exec.sh` adds the prompt contract
  and enforces the `review` role's budget
- **Claude reviewer** — when Codex review is on, a fresh sub-agent also sees the diff, plan summary, criteria,
  the checklist, and `code-standards.md`. Never sees Codex's findings. It runs under
  `references/claude-reviewer-contract.md` (inline in its prompt): ranged reads only to confirm
  a `file:line`, no git commands, at most 30 tool calls, no exploring beyond the diff.
- **Lenses**, path-gated from changed files.

Every reviewer returns the same shape: verdict, score 1–5, findings with `file:line` and
severity. The fixer works from those, not from prose.

`<runDir>/checkpoint-findings.md` (MEDIUM/LOW findings from any checkpoint spot reviews,
`[cp<n>] <severity> <file:line> <summary>`) is inlined into this panel's context under
"Known from checkpoint reviews (verify fixed or still open; do not re-report as new)".

After the Workflow, manual fixes have the same cap: two consecutive rounds per segment. On the
third gate failure, hand Jordan every failure and stop. Use one Fable review per bundle of rounds,
not one per round. Review again only past ~150 unreviewed changed lines or after a CRITICAL/HIGH
fix lands. Codex still verifies every fix.

For API and UI work, use two run dirs. Start the UI Workflow as soon as the API run has a non-empty
`captures/` directory and `context.md`. Pass `dependsOnGate: <apiRunDir>/gate-gate.json`; do not
wait for the API Workflow to finish.

## Evidence rules

Ported from a process experiment; each earned its keep on a live run.

- **Contract first.** `plan.md` carries a `## Public API contract` for any library / client / CLI /
  API-surface deliverable. Codex implements to it; the review panel scores against it; Codex plan
  review checks it for what will fail or already exists.
- **Evidence harness before features.** Phase 0 builds (or keeps runnable) a selfcheck/probe that
  exercises every capability against the live target and emits per-capability JSON
  (`{id, status: pass|fail|skip, evidence, error}`). Unit tests do not replace this live evidence.
- **Verifiers own their evidence.** Codex cannot reach a fork from its sandbox: it reports
  capabilities as implemented-unverified. Only a worker-run harness flips them. Reviewers and the
  verify pass read `STATUS.json` + the harness output, never the fixer's summary. Diagnose LIVE
  before any fix round beyond the first — fix rounds written against unseen UI/API converge only
  by luck.
- **`STATUS.json`** in the run dir: `criteria[]` (id, text, status, evidence path, round), `rounds`,
  `open_findings[]`. Seeded at plan time; merged (never truncated) by forge-core at smoke, fix
  rounds, and handoff; the handoff renders from it; a resume starts at the weakest entry.
- **Parity vs a reference implementation** when the deliverable mirrors an existing one: run both
  against the same target and diff observable results (`parity.json`). Cheap, objective, catches
  wrong assumptions about API shapes.
- **Contract captures before confirm.** Every external contract in the plan is backed by a
  worker-captured real response under `<runDir>/captures/`; Codex builds fixtures from captures,
  never by hand. Adopted after the 2026-09-15 customer_billing rework, where the invoice verb
  schema and fixtures were hand-written and wrong.
- Not adopted: per-module builder fan-out and numeric "art director" scores — the ranked issue list
  is the useful part; objective gates already provide the score.

## Judging contradictions

If a HIGH/CRITICAL finding from one reviewer is explicitly disputed by another, the
Workflow returns `needsJudge` with both sides. **The main session rules** — it already holds
the plan and both reviews — and re-invokes the Workflow with `args.rulings`. There is no
sub-agent judge and no Codex debate. In `auto`, the finding is applied (the conservative
default) and the ruling is logged.

## Smoke data a fresh fork does not have

A fresh fork seeds ONE reseller (Meridian Technology Partners). Any criterion that needs a
second partner — tenant-to-tenant moves, master-MSP/member flows, cross-partner visibility —
cannot be exercised unless the plan's `## Run Settings` says so and names the seeding recipe:
create the second reseller through the Api-Key reseller endpoint, sign its agreements, and give
it staff (see the `fork-api-seeding-techniques` memory). Without that note the smoke reports
those criteria BLOCKED-by-data, which is not a feature verdict.

## Time target

35–45 minutes after "go" for a 2–3 phase feature. The old pipeline's 92-minute run is the
baseline this is measured against; `forge-stats.py` on the run dir gives the numbers.

## Where brainstorming ends and forge begins

`brainstorming` is interactive — one question at a time, with the user. Forge is autonomous
once confirmed. They meet at a file: brainstorming writes `spec.md`; `forge dev` reads it.
Don't merge them.
