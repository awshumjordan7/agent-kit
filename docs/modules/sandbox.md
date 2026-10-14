# Sandbox module

Disabled by default. Turns on Claude Code's sandbox for every Bash command on macOS. Other platforms skip the module.
The sandbox denies reads of env files and credential folders at the operating-system level. Network git, the env
runner, the forge gate, the Codex wrapper and a few other agent-kit scripts run outside it through `excludedCommands`.
An excluded script leaves the sandbox only when it is called as a whole command, spelled exactly as its entry.
