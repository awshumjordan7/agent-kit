# Sandbox module

Disabled by default. Turns on Claude Code's sandbox for every Bash command on macOS (Seatbelt) and on Linux and WSL2
(bubblewrap). Linux needs bubblewrap and socat; the installer stops when they are missing.
The sandbox denies reads of env files and credential folders at the operating-system level. Network git, the env
runner, the forge gate, the Codex wrapper and a few other agent-kit scripts run outside it through `excludedCommands`.
An excluded script leaves the sandbox only when it is called as a whole command, spelled exactly as its entry.
The installer entry matches install.py in any checkout folder named agent-kit.
enableWeakerNetworkIsolation stays on because gh, a Go program, fails TLS certificate checks without it (x509 OSStatus -26276).
The module expects gh to keep its token in the keychain, the macOS default. With file storage, hosts.yml holds the token, and sandboxed commands can read it.
In bypassPermissions mode Claude Code allows hosts outside allowedDomains without a prompt, so the module guards files, not network hosts.
