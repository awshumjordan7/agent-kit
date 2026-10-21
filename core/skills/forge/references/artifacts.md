# Artifacts

A worker writes every artifact; the main session writes the data file or the brief and never writes
artifact HTML.

- Forge plan and QA pages render from their templates, `plan-artifact.html` and `qa-artifact.html` in
  `~/.claude/skills/forge/references/`:
  `python3 ~/.claude/skills/forge/scripts/render_artifact.py {plan|qa} --data <json> [--markdown <md>] --out <html>`.
  Forge itself drafts no QA artifact: the main session runs QA on demand with the overlay stage docs
  and has a worker render `qa-artifact.html` then.
- Any other artifact has no template: the worker writes the page following the `artifact-design` skill.
- Every artifact is glanceable: a 1-3 sentence summary at the top, tables over prose, copyable
  credentials, a links section, no changelog or update prose.
- Republishing a page over 100 KB goes to a worker. Reading a 600 KB page inline cost the main session about 150k tokens.
- A worker whose run dir is outside its working directory cannot publish from the run dir: the Artifact tool takes files only under the working directory or its scratchpad. It copies the page and its images to its scratchpad and publishes from there.
- Copy buttons go only on things a person pastes: links, access-card values, users rows, command
  blocks, and fenced code blocks; inline code gets none.
- A page that saves viewer input declares the `db` capability.
- Images go up as artifact assets, not data URIs.
