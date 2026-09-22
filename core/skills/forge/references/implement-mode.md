# forge implement — run an existing plan

For a `plan.md` that's already been written and confirmed (by a previous forge run, by
hand, or by another session). No investigation, no plan review, no review panel — just
strict, phase-by-phase execution with a gate after each phase.

**Code is written by Codex, not by this session.** The old implement mode ran everything
in-session on the top-level model; that was the most expensive path in the skill.

## Steps

1. Read `plan.md`. Confirm it has numbered phases with files and a `## Tests` section containing
   the five-column approved table, or the single line `None: <reason>`. If the phases are
   missing, stop: "this plan isn't phased — run `forge dev` on it instead." If the tests section
   is missing or malformed, stop: "this plan does not define its approved tests — return it for
   confirmation."
2. Create the run dir if absent; write `context.md` with the plan path and the repo.
3. For each phase, in order:
   - `codex-exec.sh start|resume --role impl --sandbox workspace-write --thread-file
     <runDir>/codex-impl.thread` (start on the first phase, resume after) with a prompt
     containing, all inline: the phase text, the acceptance criteria, the recon's reuse table
     when one exists, `references/code-standards.md` verbatim, and "implement only this phase;
     do not touch later phases; run the tests named in the plan for this phase". Never
     "read plan.md"; the helper prepends the prompt contract and enforces the `impl` budget.
     Start and resume detach by default; no `perl alarm` wrapper is needed.
   - Wait with `codex-exec.sh watch --max-wait 2400`; repeat when it exits 10.
   - Send one Haiku `gate`-role order:
     `gate.sh --repo <repo> --run-dir <runDir> --label phase-<n> --files <changed> --commit "<msg>" --push`.
     It runs tests and static checks, then commits and pushes only on a pass. A failure resumes the
     Codex thread with the output. A third consecutive gate failure stops the phase. Never skip a
     gate to reach the next phase.
4. After the last phase: `git status --porcelain` and a one-screen summary per phase
   (files touched, tests run). The passing phase gates already committed and pushed the work.

## What this mode is not

- Not a place to fix the plan. If a phase can't be implemented as written, stop and say
  what's wrong with the plan; don't improvise around it.
- Not reviewed. Use `forge review` afterwards if the change warrants it.
