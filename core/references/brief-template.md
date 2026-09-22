# Sub-agent brief

```
GOAL: <one sentence, the deliverable>
SCOPE: <exact files, dirs, URLs, run dir>
MAY CHANGE: <paths, or "nothing (read-only)">
MUST VERIFY: <what counts as done, with the command or check>
DO NOT: <off-limits actions>
KNOWN: <facts already established, so they are not rediscovered>
OUTPUT: <exact shape; written with the Write tool to the named path, never inline>
CAP: <max lines in the final message>. A brief cannot raise the agent file's maxTurns; split the brief instead.
```

Every Agent prompt, the main session's and forge-core's, follows this template.
Briefs are written before the spawn.
They are not edited after.
Browser steps go to the configured browser-testing agent, never to `worker`. Playwright MCP blocks file: URLs, so serve a rendered file over localhost and provide that URL.
