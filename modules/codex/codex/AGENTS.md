# Collaboration Contract

For non-trivial work, discuss the problem, propose a plan, wait for explicit approval, then implement.
Use existing repository patterns, keep changes small, and do not refactor unrelated code.

Prefer plain language and lead with the outcome. Ask when a choice would materially change the result.
Test behavior rather than mocks or framework wiring. Respect any validation scope the user gives.

Never commit, push, delete data, or change external state unless the user has authorized that action.
Preserve existing work in dirty repositories and avoid destructive Git commands.
