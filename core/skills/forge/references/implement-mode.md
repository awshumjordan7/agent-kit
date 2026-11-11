# forge implement — run an existing plan

For a `plan.md` that's already been written and confirmed (by a previous forge run, by
hand, or by another session). No investigation, no plan review, no review panel — just
strict, phase-by-phase execution with a gate after each phase.

**Code is written by the `implementer` agent, not by this session.** Its agent file sets the
model and effort.

## Steps

1. Read `plan.md`. Confirm it has numbered phases with files and a `## Tests` section containing
   the five-column approved table, or the single line `None: <reason>`. If the phases are
   missing, stop: "this plan isn't phased — run `forge build` on it instead." If the tests section
   is missing or malformed, stop: "this plan does not define its approved tests — return it for
   confirmation."
2. Create the run dir if absent; write `context.md` with the plan path and the repo. Read the
   repository's `gate.mode` (`full` or `none`) from the same config.
3. Before the first phase, switch to a new branch when the checkout is on the base branch, as
   ship-pr does.
4. For each phase, in order:
   - Build one prompt containing, all inline: the phase text, the acceptance criteria, the
     recon's reuse table when one exists, `references/code-standards.md` verbatim, and
     "implement only this phase; do not touch later phases". In gate mode `full`, add "run the
     tests named in the plan for this phase". Do not tell the implementer to read plan.md: it gets only this phase inline, so it cannot work ahead.
   - Add "progress file: `<runDir>/impl-progress-<n>.md`" to the prompt and
     spawn the `implementer` agent with that prompt and no `model`. When it
     returns `PARTIAL`, spawn it again with the same prompt plus a `## Continuation` section that
     names that progress file; allow at most 2 continuations, then stop the phase.
   - Send one `worker` order with `model: "haiku"`, because the order only runs the gate command,
     the same job forge's `gate` role does on Haiku:
     - gate mode `full`:
       `gate.sh --repo <repo> --run-dir <runDir> --label phase-<n> --files <changed> --commit "<msg>"`.
       It runs tests and static checks, then commits only on a pass.
     - gate mode `none`:
       `gate.sh --repo <repo> --run-dir <runDir> --label phase-<n> --no-stages --files <changed> --commit "<msg>"`.
       It runs no tests and commits.
   - A failed gate sends its output back to the implementer (a new
     `implementer` turn) and re-sends the order. A phase gets at
     most `MAX_FIX_ROUNDS` (2) fix rounds; then the phase stops. Never skip a gate to reach the
     next phase.
5. After the last phase: `git status --porcelain` and a one-screen summary per phase
   (files touched, tests run). The shipper then pushes the branch and opens one PR.

## What this mode is not

- Not a place to fix the plan. If a phase can't be implemented as written, stop and say
  what's wrong with the plan; don't improvise around it.
- Not reviewed. Use `forge review` afterwards if the change warrants it. The run is not exempt
  from ship-pr's ship check: it returns NEEDS_SHIP_CONFIRM until a code review is recorded (the
  plan-question rules in CLAUDE.md), or until the shipper is relaunched with `SHIP ANYWAY`.
- Not the build lane. It differs on purpose in one way: it gates the working tree and commits on
  a pass; the build lane commits first and then gates the SHA. Both use the `implementer` agent at
  its file's model and effort.
