# Private overlays

An overlay adds private settings without placing them in the public repository. Set `layers.overlay.path` in the
profile to a checkout containing `overlay.toml`.

```toml
name = "company"
description = "Company-specific tools"
requires_agent_kit = "v1.0.0"
claude_md_fragment = "CLAUDE.fragment.md"
settings_fragment = "settings.fragment.json"

[[questions]]
id = "api_key"
prompt = "Company API key"
type = "string"
default = ""
secret = true

[[mcp]]
name = "company-api"
transport = "http"
scope = "user"
url = "https://mcp.example.com/?api_key={{answers.overlay.api_key}}"
```

Overlay `hooks/`, `agents/`, `skills/`, `references/`, and `scripts/` copy over core files. JSON files in `data/`
extend the render context. Stage instructions belong in `references/stages/<stage>.md`; enable the matching
`forge.stages` value through overlay data. `requires_agent_kit` pins the public tag used during updates.

Overlay `[[questions]]` and `[[mcp]]` entries use the same fields and validation as module entries. Question
answers use the `overlay.<question id>` key in profiles and `answers.overlay.<question id>` in templates.

Keep the private denylist in the overlay repository and configure the same list as the public repository's
`DENYLIST` secret. Before merging a fork pull request, run the scan locally because fork events cannot read secrets.
