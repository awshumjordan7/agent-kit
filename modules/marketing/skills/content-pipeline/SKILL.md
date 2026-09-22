---
name: content-pipeline
description: Turn source material into reviewed, brand-consistent content and publish it safely.
---

# Content pipeline

Inputs: one source (a notes folder, a Git commit range, or a URL list) and the absolute intelligence root
`<intelRoot>` that `market-research` uses (for example `<workspace>/intelligence/`). Create an absolute run
directory `<runDir>` and write the current stage to `<runDir>/STATE.md`. Follow `references/stages.md`:
collect, analyze, render, review, publish.

Brand voice lives at `<intelRoot>/brand-voice.md`. When that file is missing, copy
`~/.claude/skills/content-pipeline/references/brand-voice.template.md` there first; never overwrite an
existing one.

Validate local inputs with `python3 ~/.claude/skills/content-pipeline/scripts/check_paths.py <root>
<path>...`. At the render stage pick one of the four modes in `references/modes.md` and follow its output
template. Render a Markdown draft using `<intelRoot>/brand-voice.md`, then run
`python3 ~/.claude/skills/content-pipeline/scripts/check_fidelity.py <source> <draft>` against the collected
source. The human edits the draft during review. Diff those edits and append only reusable rules to
`<intelRoot>/brand-voice.md`.

Publish only after explicit approval, either to a docs folder or through the shipper as a pull request.
