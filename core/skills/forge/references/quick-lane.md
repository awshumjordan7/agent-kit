# forge quick — the bug lane

The default lane for clear changes with no architecture, data-model, or downstream API-contract change.

## Candidacy — decided by the triage, before any code

The triage's `lane_verdict` is the gate. `ESCALATE_TO_DEV` is a success, not a failure:
say so in one line, hand the user the triage, and stop. Never widen a quick run to fit a
big change. Reasons that force escalation:

- an overhaul, or a file the triage couldn't fully read
- a migration, a settings/infra change, a new dependency
- a contract change visible to another product or service
- root cause not established with evidence (then the answer is "investigate more", not "guess")

## What runs

| Step | Who | Notes |
|---|---|---|
| Investigate → `triage.md` | main session + Sonnet scouts | `diagnose-before-fix`; `cgc analyze callers` for blast radius when indexed |
| Ticket | configured ticket workflow | Use it only when the installation supplies one |
| Plan → plan artifact | main session | short: the triage restated as a plan; **no Codex plan review** |
| Confirm | user | skipped in `auto` |
| Workflow | `forge-core.js`, `args.lane='quick'` | `quick-impl` only when `fullySpecified` and planned source files are within `quickReviewThreshold`; otherwise `impl` → local gate → ship → optional sandbox + smoke → review/triage → up to three counted fix rounds → handoff |
| Bot triage | Fable triage agent | When `stages.ff_review` is on, verify filtered bot comments before fixes |

The Fable general reviewer also runs when changed source files exceed `quickReviewThreshold` (default 8).
Lenses still run when paths match.
Codex roles use the prompt contract and budgets in `forge.config.json`. Claude roles use the
model and effort from the top-level `roles` block.

## Time target

15–20 minutes from "go" to handoff artifact. If a quick run is heading past 30, something
in the triage was wrong; the handoff should say what.

## What the user sees

1. The triage summary and any supplied ticket key.
2. The plan artifact. One "go".
3. `/workflows` progress if they want it.
4. The handoff artifact: what changed, gate/sandbox/smoke results, review score, manual
   checklist (one item per acceptance criterion), sandbox login + id, PR link.
5. The bot-review verdicts.
