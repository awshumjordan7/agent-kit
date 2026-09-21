---
name: diagnose-before-fix
description: >
  Investigate the actual code, logs, network responses, and runtime state BEFORE
  proposing or applying a fix when a bug is reported. Resist the urge to assume the
  cause from the symptom alone, even when an obvious-looking explanation comes to
  mind. Read the relevant code path. Re-check ground-truth (response bodies, console
  logs, DB state). State what you found before stating what you'll change. Use this
  approach whenever the user reports unexpected behavior, especially: 500 errors,
  silent failures, "this isn't working", "the dialog stays open", "data isn't
  updating", "the success callback isn't firing", "the form is broken", any case
  where multiple plausible causes exist. Also use when an earlier fix didn't work
  and the user pushes back ("instead of assuming, search for the problem", "we're
  not really figuring out here"). Do NOT use this for trivial fixes (typos,
  obvious one-liners) or when the user has explicitly told you the cause.
user-invocable: false
---

# Diagnose Before Fix

When a bug is reported, the failure mode is **jumping to a fix from the symptom**.
The user has corrected this behavior. Slow down and verify.

## Required steps before proposing a fix

1. **Read the actual code** at the suspected failure point. Don't recall it from
   memory or earlier in the session — open the file. State file paths and line
   numbers when describing what you found.
2. **Verify ground-truth state**:
   - Network tab: actual request body, response status, response body
   - Console: any errors, any logs from instrumentation
   - DB / persisted state: what's actually stored
   - Component state: what props/state values are at the moment of failure
3. **Trace the failure path** end-to-end. Don't stop at the first plausible
   suspect. Follow the chain: input → state change → effect → callback →
   network → response → state update → render.
4. **State your findings** before stating your proposed fix. The user should be
   able to follow your reasoning from observation to conclusion.

If you cannot verify ground-truth from the data you have, **ask for it** rather
than guess:

- "Can you check the Network tab response body?"
- "Can you share the relevant server-side log line?"
- "What's the actual response body the API/SDK returned?"

Adding diagnostic instrumentation (a temporary `console.log`, an extra logged
field) is a valid step. Doing so is faster than another round of speculation.

## Anti-patterns to avoid

- "It's probably X" without reading the code
- Proposing a fix in the same turn the bug was reported, before doing any
  inspection
- Treating the user's repro as already-diagnosed when they only described the
  symptom
- Recalling the API response shape "from earlier" without re-confirming it
- Brushing off a previous-round reviewer's finding as "pre-existing" without
  verifying — it may be the exact bug the user is hitting now

## Do This

```
User: The dialog isn't closing on success.

Claude: Let me trace the success path before proposing a fix.

[reads PayoutSettingsDialog.tsx:339]
The check is `if (response.resource === \`customers/${currentDwollaCustomerId}/funding-sources\`)`.
That's an exact string match. If Dwolla's actual `response.resource` differs by
anything, the entire if-block is silently skipped.

Before I change the check, can you reproduce and share the actual `response.resource`
string from the Network tab or a console.log? That tells us whether to make the
match more lenient or whether `currentDwollaCustomerId` is wrong.
```

## Don't Do This

```
User: The dialog isn't closing on success.

Claude: Probably an effect dependency issue. Let me change the deps array...
```

(No code read, no verification, just a guess that may or may not be the cause.)

## When the question is "what depends on this"

If `cgc` is on PATH and the repo is indexed (`cgc list`), run `cgc update <repo>` once,
then `cgc analyze callers <bare_name>` for the function or method under suspicion — it
resolves real call sites where grep returns every mention. Bare names only
(`is_available_in_country`, not `Product.is_available_in_country`). Grep remains the tool
for "every line that mentions this string" and the fallback when CGC is absent. Details:
`~/.claude/skills/forge/references/cgc.md`.
