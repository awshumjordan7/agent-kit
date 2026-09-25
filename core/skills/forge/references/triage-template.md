# Triage — <one-line bug title>

Written after diagnosing before fixing: read the code path and capture live evidence before
naming a cause. Every field is required; write `none` rather than leaving one blank. This file is read by the ticket step, the plan,
the implementer, and the reviewers — it is the single brief for the whole run.

## Symptom
What the user/reporter sees, in one or two sentences. Quote the error text if there is one.

## Root cause
The actual defect, with `file:line`. If you have two candidates, name both and say which
evidence separates them. "Probably" is allowed only with the evidence that makes it probable.

## Evidence
- `path/to/file.py:123` — what this line does and why it produces the symptom
- Log / response / DB state you checked, and what it showed
- Anything you ruled out and how

## Files to change
| File | Change |
|---|---|
| `path/to/file.py` | one line describing the edit |

## Blast radius
What else calls or depends on the code being changed. Use `cgc analyze callers <bare_name>`
when the repo is indexed (see `cgc.md`), grep otherwise. List callers with `file:line`.
Say explicitly if a migration, a shared serializer, an auth path, or a downstream product
an external service is involved.

## Severity
`LOW | MEDIUM | HIGH | CRITICAL` — one clause on why.

## Fix plan
Numbered steps. Each step names the file and the intent, not the code.

## Acceptance criteria
- [ ] Observable behavior, phrased so a smoke test can check it ("GET /api/x returns 200 for a customer with a cancelled sub")
- [ ] The regression test that pins it (name the test file)

## Run settings
- `lane_verdict`: `QUICK` if ≤3 files, no migration, no infra, no downstream-product contract change; else `ESCALATE_TO_DEV` with the reason
- `sandbox_tier`: always `sandbox` (the default; stub forks are not used)
- `login_mode`: `token` (v1 default)
- `ticket`: existing ticket key when supplied, else `none`
