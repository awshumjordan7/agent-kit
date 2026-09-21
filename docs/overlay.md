# Private overlays

An overlay adds private settings without placing them in the public repository. Set `layers.overlay.path` in the
profile to a checkout containing `overlay.toml`.

```toml
name = "company"
description = "Company-specific tools"
requires_agent_kit = "v1.0.0"
claude_md_fragment = "CLAUDE.fragment.md"
settings_fragment = "settings.fragment.json"
```

Overlay `hooks/`, `agents/`, `skills/`, `references/`, and `scripts/` copy over core files. JSON files in `data/`
extend the render context. Stage instructions belong in `references/stages/<stage>.md`; enable the matching
`forge.stages` value through overlay data. `requires_agent_kit` pins the public tag used during updates.

Keep the private denylist in the overlay repository and configure the same list as the public repository's
`DENYLIST` secret. Before merging a fork pull request, run the scan locally because fork events cannot read secrets.
