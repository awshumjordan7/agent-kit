---
name: content-pipeline
description: Turn source material into reviewed, brand-consistent content and publish it safely.
---

# Content pipeline

Choose one source: a notes folder, a Git commit range, or a URL list. Write the current stage to `STATE.md`.
Follow `references/stages.md`: collect, analyze, render, review, publish.

Validate local inputs with `scripts/check_paths.py`. At the render stage pick one of the four modes in
`references/modes.md` and follow its output template. Render a Markdown draft using `brand-voice.md` when
it exists, then run `scripts/check_fidelity.py` against the collected source. The human edits the draft during
review. Diff those edits and append only reusable rules to `brand-voice.md`.

Publish only after explicit approval, either to a docs folder or through the shipper as a pull request.
