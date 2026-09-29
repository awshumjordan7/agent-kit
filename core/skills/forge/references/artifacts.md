# Artifacts

Every artifact of any kind is produced by a worker from a template plus a data file the main session
writes; the main session never writes artifact HTML.

- Templates: `plan-artifact.html`, `qa-artifact.html`, and `generic-artifact.html` in
  `~/.claude/skills/forge/references/`.
- The one renderer: `python3 ~/.claude/skills/forge/scripts/render_artifact.py {plan|qa|generic} --data <json> [--markdown <md>] --out <html>`.
  No worker writes its own renderer.
- Every artifact is glanceable: a 1-3 sentence summary at the top, tables over prose, copyable
  credentials, a links section, no changelog or update prose.
- Copy buttons go only on things a person pastes: links, access-card values, users rows, command
  blocks, and fenced code blocks; inline code gets none.
