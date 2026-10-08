```
# STATE - <run slug>
Updated: <ISO timestamp>   Session: <n>   Lane: <build|review>
Read this file first. Do not read plan.md, the Codex logs, or other run-dir files unless a step below points at them.
## Goal and standing rules
- <YYYY-MM-DD> "<the user's words, verbatim>" (<source: session8 or relay name>)
  (optional, only when the user asked to hand off themselves: add the bullet - Handoff: manual (<date>, "<the user's words>"))
## Open questions to the user
- [open] <YYYY-MM-DD> <question>
- [answered <YYYY-MM-DD>] <question> -> "<the user's answer, verbatim>"
  (or the single line "- None" when there are no questions)
## Now
<one to three lines: what is true right now, what is in flight>
## Next
1. <next action, who does it (main session / worker / Codex / steward)>
## Blockers / waiting on the user
- <item or "none">
## Pointers
- plan: <path>   decisions: <path>   STATUS.json: <path>   captures: <path>
- PR(s): <url>   branch: <name>   base: <name>   worktree: <path or "main checkout">
- sandbox: <id> preview <url> (details in sandbox.json)
- live sandboxes/forks: <id> created <YYYY-MM-DD> - <keep: reason | teardown: when> (one line each, or "none"; one older than a day with no keep reason also goes under Blockers)
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
