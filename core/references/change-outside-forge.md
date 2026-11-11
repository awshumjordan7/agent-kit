# A code change outside forge

These steps apply to a main-session edit, a `worker` change, or an `implementer` spawn. Forge runs skip them.

1. **Run dir.** The change gets its own run dir: `<workflow dir>/<YYYY-MM-DD>-<slug>/`. `<workflow dir>` is the
   `.workflow/` folder that holds the session's own run dir, or `<repo>/.workflow/` when the session has none.
   Create it with an empty `decisions.md` before any worker starts, and name it in every brief for the change.
2. **Label.** Pick a label once per change (default `change`). A follow-up in the same run dir takes a new label.
   The review command, every ship_record call and the shipper brief name that label.
3. **With a plan.** Write `<run dir>/plan.md`. Run
   `~/.claude/skills/forge/scripts/build-plan-review-prompt.sh --run-dir <run dir> --repo-dir <repo>` and the
   `plan-review` role. Then wait for the user's go. When the plan has a `## Changelog` section, write
   `<run dir>/user-ok.md` with the user's approval quoted word for word and the date, as forge does (forge SKILL.md step 4).
4. **Code review, with or without a plan.** After the change, run
   `~/.claude/skills/forge/scripts/build-code-review-prompt.sh --run-dir <run dir> --repo-dir <repo> --label <label>`
   and the `review` role. Record the verdict with `ship_record.py verdict --repo <repo> --run-dir <run dir>
   --stage review --label <label> --provider <p> --model <m> --verdict <v>`.
5. **Who reviews.** The role's provider decides: `codex` runs `codex-exec.sh`, and `claude` runs the `reviewer`
   agent with the printed paths.
6. **Ship confirm.** When the shipper returns `NEEDS_SHIP_CONFIRM`, ask "Ship without <what is missing>?". Only on
   yes, relaunch it with a new brief file that holds a `SHIP ANYWAY: "<the user's words>"` line. Briefs are not
   edited after a spawn, and ship-pr reads that line only from the brief.
