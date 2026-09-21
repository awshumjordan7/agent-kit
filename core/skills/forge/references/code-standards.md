# Code standards

Injected into every forge implementer, reviewer, and fixer prompt. Codex and
sub-agents never read ~/.claude/CLAUDE.md, so these rules travel with the prompt.
Generated verbatim from CLAUDE.md sections "Don't", "Comments", "Tests" —
do not edit here; edit CLAUDE.md and run `doctor.py --fix`.

### Don't

- Start implementing before confirmation
- Over-engineer or add speculative abstractions (YAGNI)
- Catch broad exceptions (`except Exception`) -- catch specific errors
- Use outdated typing (`Optional[str]`, `List[int]`) -- use `str | None`, `list[int]`
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

Test behavior, not wiring. Before writing a test, ask: if this fails, did
the product break -- or did my mock setup change?

Never write tests that:

- Assert a mock returned what it was configured to return, or that mocks
  were called in the order the test wired them
- Re-derive the implementation (asserting `hash_code() == hashlib.sha256(...)`)
- Duplicate coverage an existing higher-level suite already provides
- Add parametrize cases that exercise an already-covered code path
- Test the framework (URL routing resolves, the ORM saves)

A small set of behavior-pinning tests beats exhaustive combinations.
