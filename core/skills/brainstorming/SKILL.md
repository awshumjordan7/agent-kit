---
name: brainstorming
description: >
  Structured discussion skill that produces a forge plan before implementation begins.
  Guides focused exploration, grounds the design in the actual codebase, presents 2-3
  approaches with trade-offs, includes test strategy, and hands the agreed approach to forge.
  Use whenever: "brainstorm", "discuss this feature", "let's design", "new feature",
  "I want to build", "explore approaches", "what do you think about building", "let's think
  through", "design session", or before starting a complex feature that needs upfront
  discussion. Also use when the user wants to explore trade-offs before committing to an
  approach. Do NOT use for: bug fixes, quick tweaks, tasks where the user already has a plan,
  or when the user says "just do it" / "quick fix". If the user already has a plan document,
  use forge (or `forge implement`) instead.
---

# Brainstorming

Structured discussion that produces a forge plan before implementation begins. This skill is for
exploration and design — it produces a plan, not code.

## Phase 1: Understand

Ask every independent question in the same turn; go one at a time only when the next question
depends on the answer.

**Ground in the codebase first.** When the feature touches existing code, before (or
alongside) questioning, map the current state instead of assuming it: spawn one or more
`scout` agents (Agent tool, `subagent_type: "scout"`; it pins Sonnet, while built-in agent
types inherit the session model) in parallel to trace entry points, relevant files, and
existing patterns, and have them report the key files to read. Use what they find
to ask sharper questions and make the approaches concrete. Skip this for greenfield work with
no existing code to explore.

Areas to explore (follow the conversation, not all at once):
- **What exists today** — current state, relevant code, existing patterns (from the exploration above).
- **What needs to change** — the gap between current and desired state.
- **Who's affected** — users, systems, downstream consumers, other teams.
- **Constraints** — performance, backwards compatibility, timeline, technical debt, infra.
- **Success criteria** — how do we know this is done and working?

Rules: ask every independent question in the same turn; go one at a time only when the next
question depends on the answer. Summarize understanding after the answers to confirm alignment;
on a vague answer, ask a specific follow-up rather than moving on with ambiguity; stop exploring
once you have enough to propose approaches.

## Phase 2: Approaches

Present 2-3 genuinely viable approaches — no strawman just to flatter another option. For each:

1. **Summary** — one paragraph.
2. **How it works** — enough implementation detail to judge feasibility.
3. **Test strategy** — what to test, test types, which tests block merge.

Then a comparison table with concrete Low/Medium/High ratings and one-line trade-offs (no
paragraphs in cells):

| Aspect | Approach A | Approach B | Approach C |
|--------|-----------|-----------|-----------|
| Effort | | | |
| Risk | | | |
| Complexity | | | |
| Maintainability | | | |
| Trade-offs | | | |

## Phase 3: Test Strategy

For each approach: what to test (core behaviors, edge cases, failure modes); test types
(unit / integration / e2e / manual / load — be specific); blockers vs nice-to-have; and
what's hard to test (be honest — a hard-to-test approach is a real trade-off that affects the
decision). Test strategy is part of the design, not an afterthought.

## Phase 4: Decision

When the user picks an approach (or a hybrid): confirm the choice; capture the **rationale**
(why this over the others — as valuable as the approach itself for future "why did we do it
this way?"); note any hybrid elements borrowed from other approaches.

## Phase 5: Hand off to forge

Before writing the plan, check for gaps, contradictions, unstated assumptions, and missing
context. Fix what you find so someone reading it cold can understand the decisions.

Write the agreed approach, key decisions, scope, and test strategy to `<runDir>/plan.md` in
forge's plan shape:

- Summary
- Public API contract
- Phases
- Acceptance criteria
- Run settings

Do not render a brainstorming artifact or a separate spec document. Invoke `/forge <plan path>`
for the default forge lane. When the user already has a phased plan, route directly to
`/forge implement <plan path>`.

Example: "Plan written to `.workflow/2026-04-13-auth-redesign/plan.md`. Ready for
`/forge .workflow/2026-04-13-auth-redesign/plan.md` when you are."

See `references/examples.md` for worked examples of each phase.

## Grounding with the call graph

When grounding a design in the codebase, and `cgc` is on PATH with the repo indexed
(`cgc list`): `cgc update <repo>`, then `cgc analyze callers <bare_name>` /
`cgc analyze calls <bare_name>` for the functions the feature would touch. It answers
"who depends on this" precisely; grep still answers "where is this mentioned". Fall back
to grep when CGC is absent. Details: `~/.claude/skills/forge/references/cgc.md`.
