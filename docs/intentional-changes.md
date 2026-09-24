# Intentional changes from the private setup

| Source | Public change |
|---|---|
| `.claude/settings.json:51,72,84,96,127,177,189,230` | Machine-local webhook hooks move to the local layer. |
| `.claude/settings.json:62,117` | The macOS sound command moves to the local layer. |
| `.claude/CLAUDE.md:22,139-141` | Internal library and MCP guidance is omitted. |
| `.claude/CLAUDE.md` routing table | Private ticket, sandbox, and review agents are omitted. |
| `.claude/agents/scout.md:9-11,33-34` | Company repositories and services are replaced with generic workspace guidance. |
| `.claude/agents/reviewer.md:9` | Company-specific workspace wording is removed. |
| `.claude/agents/spot-reviewer.md:9` | Company-specific workspace wording is removed. |
| `.claude/references/env-recipe.md:14,25` | Private paths and service assumptions are replaced with project guidance. |
| `.claude/references/brief-template.md:17` | The private sandbox agent name is replaced with the core `browser` agent. |
