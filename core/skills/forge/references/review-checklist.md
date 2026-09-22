# Review checklist

- Data-model correctness — Confirm stored and derived state preserves the intended invariants across reads, writes, and migrations.
- Edge cases — Check boundary values, empty or missing inputs, partial state, retries, and concurrency-sensitive paths.
- Security — Trace trust boundaries, authorization, validation, secret handling, injection risks, and unsafe external calls.
- Performance — Look for avoidable repeated work, N+1 access, unbounded operations, blocking hot paths, and resource leaks.
- Error handling — Ensure failures retain useful context, return the right status, and cannot be mistaken for success.
- Naming consistency — Verify new names match repository vocabulary and describe the same concepts consistently across layers.
- Test quality vs coverage — Require behavior-pinning tests for the planned risks without permutation grids, framework tests, or redundant coverage.
- Correctness traps — Look specifically for wrong assumptions, null handling, off-by-one behavior, races, and code that does not actually satisfy the plan or criteria.
- Silent failures — Flag swallowed errors, success-shaped fallbacks, authorization failures converted to 500s, and mocks or defaults that disable the behavior a test claims to exercise.
- Evidence discipline — Every finding cites a file:line from the diff file or excerpts; a repository read only confirms such a line. No findings from exploring code the change does not touch.
