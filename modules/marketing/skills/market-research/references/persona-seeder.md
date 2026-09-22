# Persona seed scout

## Purpose

Write the first version of a persona from what the team already believes, with every belief marked as an
assumption so the evidence stages can confirm or kill it.

## Inputs

- `{persona}` name: descriptive, not a person's name.
- The starting context: team knowledge, prior research, expert input, or a hypothesis worth testing.
- Where that context came from, per item.
- `{company}`, `{product}` and `{audience}` as the skill resolved them.

## Evidence and confidence

Grade every claim before it enters the output:

- **Tier 1 - direct primary source.** First-hand material: an interview, a call transcript, a support
  ticket, a survey response, or a signed statement from the party the claim is about.
- **Tier 2 - corroborated secondary source.** An independent third party confirmed by a second
  independent source: review platforms, trade coverage, analyst write-ups, distributor listings.
- **Tier 3 - single uncorroborated or inferred.** One unconfirmed mention, a vendor self-claim, or your
  own reasoning from other facts.

Corroboration rule: a claim reaches tier 1 or tier 2 only with a dated link. Without a dated link the
claim is tier 3 whatever its origin. Almost everything in a seed persona is tier 3, and that is the point
of this stage: it makes the assumptions visible so later evidence can promote or demote them. Label every
inference as an inference in the sentence that makes it.

## Steps

1. **Collect the starting context.** What the team believes about this persona, and which of those
   beliefs are hypotheses rather than observations.
2. **Record the origin of each item.** Team knowledge, prior research, expert input, or assumption. An
   item with no origin is an assumption.
3. **Fill only the sections you have context for.** Core identity, buying behaviour, information habits,
   sales and marketing signals, product and support needs.
4. **Leave demographics and psychographics blank unless you have specific knowledge.** A plausible guess
   here becomes a fact three documents later. Blank is the correct answer.
5. **Mark every assumption in place,** in the line it appears on, not only in a footnote.
6. **Name the evidence that would settle each assumption** - the interview, review or ticket type that
   would confirm or contradict it.
7. **Check the persona before saving:** descriptive name, sourced context, marked assumptions, blank
   sections left blank, and the evidence count at zero.

## Output template

Write to `intelligence/personas/{persona}/profile.md`. Use the actual current date.

```markdown
# Persona: {persona}

**First created:** {YYYY-MM-DD}
**Last updated:** {YYYY-MM-DD}
**Status:** seeded - no evidence collected yet

## Core identity
- **Role and department:**
- **Organisation size and type:**
- **Industry or segment:** {audience}
- **Location:**

## Demographics
{Only with specific knowledge. Otherwise: "unknown - no evidence".}

## Psychographics
{Only with specific knowledge. Otherwise: "unknown - no evidence".}

## Buying behaviour
- **Buying process:** {*assumption* where unproven}
- **Decision criteria:**
- **Budget authority:**
- **Evaluation timeline:**
- **Other stakeholders:**

## Information habits
- **Channels:**
- **Content types:**
- **Trusted sources:**

## Sales and marketing signals
- **Expected objections:**
- **Messaging that may resonate:**
- **Proof points that may matter:**

## Product and support needs
- **Capability priorities:**
- **Support preferences:**
- **Onboarding needs:**

## Assumptions to validate
| Assumption | Origin | Evidence that would settle it |
|---|---|---|
| | | |

## Evidence summary
- **Evidence items:** 0
- **Date range:** none
- **Note:** seeded from team context; evidence collection needed before any section is treated as fact.
```

## Evidence ledger

Every material claim in the output gets one row. A seed persona's rows are mostly tier 3 by design, and
the origin column stands in for a URL when the origin is a person rather than a document.

| claim | source URL | date | tier |
|---|---|---|---|
| | | | |

## QA gate

The brief fails when any box is unchecked:

- [ ] Every claim in the output has an evidence-ledger row with an origin and a date.
- [ ] Every inference is labelled as an inference rather than stated as fact.
- [ ] Every assumption is marked in the line where it appears, not only in a summary table.
- [ ] No required section of the output template is empty and no `{placeholder}` is left unresolved;
      sections without context read "unknown - no evidence".
- [ ] Demographics and psychographics are blank unless specific knowledge supports them.
- [ ] The evidence count reads zero and the persona is labelled as seeded.

## Handoff

Next brief: `evidence-collector.md`, which reads `intelligence/personas/{persona}/profile.md` and files
evidence against the assumptions listed there.
