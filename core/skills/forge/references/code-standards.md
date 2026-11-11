# Code standards

The rules for writing and reviewing code, comments and tests. Forge puts this file into every
implementer, reviewer and fixer prompt, and CLAUDE.md points the main session here. Edit this file directly.

### Don't

- Over-engineer or add speculative abstractions (YAGNI)
- Catch broad exceptions (`except Exception`) -- catch specific errors
- Refactor working code you weren't asked about
- Make up dependency versions -- use package manager to find latest

### Comments

Comments are for the next reader of the code, not the reviewer of this diff.
Most methods need no comment. When one is needed, it states something the
code cannot show -- a constraint, a trap, a "why" -- in one or two sentences.

The amnesia test: would this comment exist if you had written the file cold,
with no prior conversation? If it only exists because we discussed it, delete
it -- the back-and-forth is not context the file's readers have. A real
constraint learned in discussion passes the test: it exists because the
constraint is true, not because it was discussed. State the constraint, never
the conversation.

Never write comments that:

- Restate the code (`# Proceed with creation` above a transaction block,
  `# Case A / Case B` labels on if/elif branches)
- Reference the session, plan, or conversation: "as discussed", "per the
  spec", "(plan C2.0.x)", "addresses review feedback". The session ends;
  the comment doesn't.
- Point at files not in the repo (local plan docs, `.workflow/` artifacts,
  scratch notes). If the reason matters, state the reason itself.
- Justify the change to a reviewer ("this is correct because...") -- that
  belongs in the PR description
- Reference other PRs, or leave commented-out code behind

Jira IDs in comments are allowed only when the comment still makes sense
without opening the ticket.

### Tests

Tests cover the critical path only: behavior that, when it breaks, stops a user's main task, loses or
corrupts data, or opens a security hole. Each test names the risk it pins. Claude chooses the tests and
does not ask the user to approve them separately. A plan lists them in its `## Tests` table (a no-tests
plan says `None: <reason>`), and approving the plan approves them. Add only the tests in that table. A
change with no plan gets a test only when it touches the critical path. Repositories with forge
`gate.mode: none` have no tests. Do not add or run tests, lint, typecheck, migrations, Semgrep, or parity
commands in those repositories.

Test behavior, not wiring. Before writing a test, ask: if this fails, did
the product break -- or did my mock setup change?

Never write tests that:

- Assert a mock returned what it was configured to return, or that mocks
  were called in the order the test wired them
- Re-derive the implementation (asserting `hash_code() == hashlib.sha256(...)`)
- Duplicate existing higher-level coverage, or add parametrize cases for an already-covered code path
- Test the framework (URL routing resolves, the ORM saves)

A small set of behavior-pinning tests beats exhaustive combinations.
