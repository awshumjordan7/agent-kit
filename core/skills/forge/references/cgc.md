# CodeGraphContext in forge

`cgc` builds a call graph of a repo (which function calls which, who inherits what) and
answers three questions better than grep: **who calls this**, **what does this call**, and
**how complex is this**. Everything else stays grep. Forge uses it in recon and triage, and
`dx-audit` uses it for dependents of changed endpoints.

## Guard, every time

    command -v cgc >/dev/null && cgc list 2>/dev/null | grep -q "<repo path>"

If that fails: use grep and move on. Forge never fails because CGC is missing or stale.

## Refresh first

    cgc update <repo path>

Seconds on a large Python API repository. Run it once per run, before any query — the index is a snapshot
from the last time someone ran it. No `cgc watch`, no git hooks.

## The four commands

| Question | Command | Notes |
|---|---|---|
| Who calls X? | `cgc analyze callers <bare_name>` | **bare names only** — `is_available_in_country`, not `Product.is_available_in_country` |
| What does X call? | `cgc analyze calls <bare_name>` | |
| Which classes override `save`? | `cgc analyze overrides save` | exact in the measured repository (13/13) |
| What's complex here? | `cgc analyze complexity --file <path>` or repo-wide | no grep equivalent |

`cgc query "<Cypher>"` is the escape hatch for anything else.

## Quirks

- Same-name collisions inflate "most-called" answers (`get`, `save`); ask about distinctive names.
- `cgc analyze dead-code` flags Django/DRF hooks (`save_model`, `handle`, `get_queryset`,
  `perform_*`, `validate_*`, migration `forward`/`backward`, serializer `create`/`update`).
  Treat every dead-code hit as a candidate, never a finding.
- Dynamic Python (`getattr`, dict-driven serialization, raw SQL) is invisible to the graph.
  Grep is still the fallback for "every mention of this string".
- The embedded DB (`redis-server` + `falkor_worker`) stays running after any command; that's the
  storage, not a watcher.

## Repository setup

A `.cgcignore` at the repo root scopes indexing to Python — it excludes stale worktrees,
`reports/`, `.workflow/`, and all HTML/CSS/JS (a 3.7 MB coverage HTML crashed the indexer
before this). Migrations are included on purpose. The file is kept out of git via
`.git/info/exclude`. For a new repo: copy the ignore file, exclude it the same way, run
`cgc index <repo>` once (~20 s in the measured repository).
