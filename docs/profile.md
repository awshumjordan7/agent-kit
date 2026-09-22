# Profile

`~/.ai-setup/profile.json` records the installed layers, enabled modules, answers, agent limits, forge roles, and
doctor settings. Schema 1 rejects unknown keys so misspelled settings fail early.

| Section | Purpose |
|---|---|
| `layers` | core checkout, optional overlay checkout, and local directory |
| `modules` | one Boolean per shipped module |
| `answers` | module question values; secret answers are redacted from dry runs |
| `agents` | `model`, `maxTurns`, and optional `effort` per agent |
| `forge` | provider roles, optional stages, gate commands, and workspace |
| `ship_pr` | base branch overrides by `owner/repo` |
| `doctor` | repository roots and Codex mirror settings |
| `auto_update` | allow the daily hook to apply available updates |

Use `install --profile FILE --yes` to replay a profile without prompts. Paths beginning with `~` expand when the
profile is loaded. Later layer data overrides earlier values through the normal deep-merge rules. When `--home`
points somewhere other than `~/.claude`, MCP registration and the self-check's MCP list probe are skipped because
the Claude CLI writes user-scoped servers to the default home.

On later installs, files that are no longer managed are retired when unchanged and preserved with a notice when locally modified.
