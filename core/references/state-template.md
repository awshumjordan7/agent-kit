```
# STATE - <run slug>
Updated: <ISO timestamp>   Session: <n>   Lane: <build|review>
Read this file first. Do not read plan.md, the Codex logs, or other run-dir files unless a step below points at them.
## Goal and standing rules
- <YYYY-MM-DD> "<the user's words, verbatim>" (<source: session8 or relay name>)
  (Only rules and goals that still bind. Decision answers and one-off messages stay in user-log.md, which user_log.py writes; cite one as "user-log <key>" when a step depends on it.)
  (optional, only when the user asked to hand off themselves: add the bullet - Handoff: manual (<date>, "<the user's words>"))
## Open questions to the user
- [open] <YYYY-MM-DD> <question>
- [answered <YYYY-MM-DD>] <question> -> "<the user's answer, verbatim>"
  (or the single line "- None" when there are no questions)
## Now
<one to three lines: what is true right now, what is in flight. End each with (verified: <file or command>) or (inferred).>
## Next
1. <next action, who does it (main session / worker / Codex / steward)>
   (Next holds live steps only. When a step is replaced, delete it or tag it "(superseded by <id>)". handoff.py moves tagged entries to <runDir>/STATE-archive.md.)
## Blockers / waiting on the user
- <item or "none">
## Pointers
- plan: <path>   decisions: <path>   captures: <path>
- PR(s): <url>   branch: <name>   base: <name>   worktree: <path or "main checkout">
- live sandboxes/forks (from QA the main session ran on demand): <id> created <YYYY-MM-DD> - <keep: reason | teardown: when> (one line each, or "none"; one older than a day with no keep reason also goes under Blockers)
- QA verdicts: <round N: pass/fail/blocked counts read from the QA artifact's qa-results db on <date> | not read: <reason> | no QA artifact>
- Workflow: <runId> (same-session resume only; a new session relaunches from launch-args.json)
- optional review stage: <status or NOT configured>
## Do not redo
- <verified facts a new session must not re-derive>
## Feedback (issues, pain points, suggestions from this session; delete the section if none)
- <one line per item> (also filed with report_issue.py)
```

Rewritten whole, never appended. Written after the plan, after the Workflow
returns, after every manual fix round, and before a session handoff. A new
session reads this file first and nothing else until it needs to.

`Goal and standing rules` and `Open questions to the user` are required:
handoff.py refuses a STATE.md where either heading is missing or has no bullet
(`- None` counts). Copy the user's words in quotes, never a paraphrase; add a
dated bullet when the user changes the goal or a rule instead of rewording an
old one. Mark a question `[answered <date>]` with the user's answer in quotes;
remove it after the next handoff lists it under "Close these".

Before reusing an `(inferred)` line in published text (a PR body, ticket or message), open its source and re-verify it.

Keep STATE.md under about 30 KB (about 8k tokens), measured with `wc -c`. `Do not redo` holds facts a new session still needs. History of merged PRs and finished runs moves to the decisions file named under Pointers (create `<runDir>/decisions.md` when it is missing), with one pointer line left here. handoff.py moves tagged Next entries to STATE-archive.md and warns when the file is still over 30 KB.

Write QA counts only from a qa-results read made in this session and filtered to the current round. When the read is not possible, for example when the ArtifactData tool is missing, write `not read` and the reason, never a count carried over from memory.
