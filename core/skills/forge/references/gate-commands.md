# Gate commands

Forge reads commands from the repository entry in `forge.config.json`. Use only the configured lint, typecheck, migration, test, and Semgrep commands. Do not infer service setup or broaden test scope.

When a command needs credentials or local services, run it through the repository's documented environment wrapper. Never print environment variables. Treat unavailable services as an environmental failure and report the command and concise error.
