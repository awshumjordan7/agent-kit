# Playwright

Disabled by default. Registers the captured headless, isolated Playwright MCP command for browser verification.

The core `browser` agent (`core/agents/browser.md`) carries its own copy of this server inline, so it works even when this module is off or the user-scope server is disabled for a project. Keep its `args` in step with `module.toml`. Neither config passes `--browser`, so Playwright MCP uses the Chrome channel: Chrome must be installed.
