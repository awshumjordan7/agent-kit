# Modules

Modules can declare Claude MCP servers with `[[mcp]]`. HTTP servers may set string-valued `headers`; values use
the same answer-template syntax as commands, arguments, environment variables, and URLs. Answers marked secret
are redacted from dry-run output.

When a previously enabled module is switched off, the next install or update removes MCP servers declared by
that module. Servers not declared by agent-kit are left unchanged.
