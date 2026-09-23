# forge implement — run an existing plan

For a `plan.md` that's already been written and confirmed (by a previous forge run, by
hand, or by another session). No investigation, no plan review, no review panel — just
strict, phase-by-phase execution with a gate after each phase.

**Code is written by the `roles.impl` provider, not by this session.** Read `roles.impl` from
`~/.claude/skills/forge/forge.config.json`. The old implement mode ran everything in-session
on the top-level model; that was the most expensive path in the skill.

## Steps

1. Read `plan.md`. Confirm it has numbered phases with files and a `## Tests` section containing
   the five-column approved table, or the single line `None: <reason>`. If the phases are
   missing, stop: "this plan isn't phased — run `forge dev` on it instead." If the tests section
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
     tests named in the plan for this phase". Never "read plan.md".
   - `provider: claude`: add "progress file: `<runDir>/impl-progress-<n>.md`" to the prompt and
     spawn the `claude-implementer` agent with the role's `model` and that prompt. When it
     returns `PARTIAL`, spawn it again with the same prompt plus a `## Continuation` section that
     names that progress file; allow at most 2 continuations, then stop the phase.
   - `provider: codex`: `codex-exec.sh start|resume --role impl --sandbox workspace-write
     --thread-file <runDir>/codex-impl.thread` (start on the first phase, resume after) with
     that prompt. The helper prepends the prompt contract and enforces the `impl` budget.
     Start and resume detach by default; no `perl alarm` wrapper is needed. Wait with
     `codex-exec.sh watch --max-wait 2400`; repeat when it exits 10.
   - Send one `worker` order with `model: "haiku"`:
     - gate mode `full`:
       `gate.sh --repo <repo> --run-dir <runDir> --label phase-<n> --files <changed> --commit "<msg>"`.
       It runs tests and static checks, then commits only on a pass.
     - gate mode `none`:
       `gate.sh --repo <repo> --run-dir <runDir> --label phase-<n> --no-stages --files <changed> --commit "<msg>"`.
       It runs no tests and commits.
   - Never pass `--push`. A failed gate sends its output back to the implementer (resume the
     Codex thread, or a new `claude-implementer` turn) and re-sends the order. A phase gets at
     most `MAX_FIX_ROUNDS` (2) fix rounds; then the phase stops. Never skip a gate to reach the
     next phase.
5. After the last phase: `git status --porcelain` and a one-screen summary per phase
   (files touched, tests run). The shipper then pushes the branch and opens one PR.

## What this mode is not

- Not a place to fix the plan. If a phase can't be implemented as written, stop and say
  what's wrong with the plan; don't improvise around it.
- Not reviewed. Use `forge review` afterwards if the change warrants it.
- Not the build lane. It differs on purpose in two ways:
  - It gates the working tree and commits on a pass; the build lane commits first and then
    gates the SHA.
  - It always uses `roles.impl`, because a plan run this way is a full plan.
