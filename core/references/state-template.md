```
# STATE - <run slug>
Updated: <ISO timestamp>   Session: <n>   Lane: <build|review>
Read this file first. Do not read plan.md, the Codex logs, or other run-dir files unless a step below points at them.
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
