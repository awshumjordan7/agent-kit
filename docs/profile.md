# Profile

`~/.ai-setup/profile.json` records the installed layers, enabled modules, answers, agent limits, forge roles, and
doctor settings. Schema 1 rejects unknown keys so misspelled settings fail early.

| Section | Purpose |
|---|---|
| `layers` | core checkout, optional overlay checkout, and local directory |
| `modules` | one Boolean per shipped module |
| `answers` | module question values; secret answers are redacted from dry runs |
| `agents` | `model`, `maxTurns`, and optional `effort` per agent; see below |
| `forge` | provider roles, optional stages, gate commands, and workspace |
| `ship_pr` | base branch overrides by `owner/repo` |
| `doctor` | repository roots and Codex mirror settings |
| `auto_update` | allow the daily hook to apply available updates |

Agent settings have two sources: the agent file's frontmatter and the profile's `agents.<name>` entry. At install
the profile wins: each `model`, `maxTurns`, or `effort` it sets replaces the frontmatter value. An omitted key, or a
`null` `maxTurns` or `effort`, means no override: the repo default from `core/profile.default.json` applies when one
exists, otherwise the frontmatter value stays. `model` cannot be `null`; it must be a string.

`install` and `update` save only overrides under `agents` and `forge`: a value equal to the repo default is left out
of `profile.json`, so later default changes reach every update. Other sections are saved in full. If a pruned save
would load differently, the full values are saved and a `profile not pruned` warning names the first differing path.
`install.py update --check` lists each saved override as `profile override: <path> = <value> (repo default: <value>)`.
Install, update, and check warn once per profile agent name with no agent file and per `forge.roles` name outside
`impl`, `quick-impl`, `review`, and `plan-review`.

Use `install --profile FILE --yes` to replay a profile without prompts. Paths beginning with `~` expand when the
profile is loaded. Later layer data overrides earlier values through the normal deep-merge rules. When `--home`
points somewhere other than `~/.claude`, MCP registration and the self-check's MCP list probe are skipped because
the Claude CLI writes user-scoped servers to the default home.

On later installs, files that are no longer managed are retired when unchanged and preserved with a notice when locally modified.
