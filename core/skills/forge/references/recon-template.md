# Recon — <feature name>

Written by the main session (Sonnet scouts do the reading) before the plan for a
build-lane run. Its one job: make sure the plan reuses what already exists instead of
inventing a parallel version of it. Read by the plan step, the Codex plan review, and
the reviewers.

## What the spec asks for
Three to five sentences restating `spec.md` in terms of the codebase (which apps, models,
endpoints, screens).

## Already exists — reuse
| Thing | Where | How it applies |
|---|---|---|
| model / field / manager | `app/models/x.py:NN` | e.g. "pricing_visibility already lives on MemberLink; extend, don't add" |
| endpoint / view / serializer | `app/api/views.py:NN` | |
| service / helper / utility | `app/services/x.py:NN` | |
| Repository convention | local documentation | error handling / client / typing rules that apply |
| UI component / route | `src/...` | |

## Callers of anything being changed
For each function/class the spec will touch: `cgc analyze callers <bare_name>` (if indexed,
after `cgc update`), else grep. List with `file:line`. This is the review panel's blast-radius
input — be complete here so nobody has to redo it.

## Patterns to follow
The two or three existing implementations most like what's being built, with paths. The
implementer copies their shape.

## Constraints found
- Migrations needed? Reversible?
- Permissions / RBAC paths involved (triggers the security lens)
- API contract changes visible to downstream products
- Feature flags / settings that gate the area

## Open questions
Anything the spec leaves ambiguous. In an attended run these go to the user before the plan;
in `auto`, the plan picks the reading closest to the spec text and logs it in `decisions.md`.

## Run settings
- `sandbox_tier`: always `sandbox` (Jordan's rule; stub forks are not used)
- `login_mode`: `token` (v1 default)
- `lenses_expected`: which of `security` / `dx-audit` / `design-audit` the changed paths will trigger
