# Sub-agent brief

```
GOAL: <one sentence, the deliverable>
SCOPE: <exact files, dirs, URLs, run dir>
MAY CHANGE: <paths, or "nothing (read-only)">, plus <runDir>/scratch/ for grep dumps, downloads and other scratch files (run `mkdir -p` on it if missing); nothing else is written
MUST VERIFY: <what counts as done, with the command or check>
DO NOT: <off-limits actions>
KNOWN: <facts already established, so they are not rediscovered>
OUTPUT: <exact shape; written with the Write tool to the named path, never inline; name the file recon-*, result-*, capture-* or locate-*>
CAP: <max lines in the final message>. A brief cannot raise the agent file's maxTurns; split the brief instead.
```

Size SCOPE so the work fits about 40 tool calls; a larger question is two briefs.
A sub-agent's Write tool refuses `.md` names that start with `report`, `summary`, `findings` or `analysis`, so OUTPUT files use the `recon-`, `result-`, `capture-` or `locate-` prefixes.
Every Agent prompt the main session writes follows this template.
Forge-internal agents (reviewer, triage, judge) get their prompts from forge and return their schema in the final message instead of writing an OUTPUT file.
Briefs are written before the spawn: the brief file's write must succeed in a tool round before the Agent call that uses it, never in the same message, where a blocked write still lets the agent start without its brief.
They are not edited after.
Write briefs with the Write tool, or in Bash only with a quoted heredoc (`<<'EOF'`).
Never tell an agent to delete a directory (`rm -rf` is denied); if a dir must be emptied, a worker runs `find <dir> -mindepth 1 -delete` then `rmdir <dir>`.
Browser steps go to the configured browser-testing agent, never to `worker`. Playwright MCP blocks file: URLs, so serve a rendered file over localhost and provide that URL.
A brief that hands an agent a file holding cookies, tokens, headers, or typed values (a Playwright trace.zip, whose action titles and params include filled passwords; a HAR; an auth storage-state file) names `python3 ~/.claude/skills/forge/scripts/trace-read.py <file>` in KNOWN as the structure-only probe (it prints redacted action and network rows), or `zipinfo -1 <file>` for a file listing, and forbids printing raw contents or action titles from it.
