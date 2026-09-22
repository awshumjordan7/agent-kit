# Persona synthesizer

## Purpose

Rewrite the persona from the analysed evidence: one file per role, every section citing the evidence
behind it, with the contradictions, the unknowns and the interviews still worth running.

## Inputs

- `intelligence/personas/{persona}/analysis.md` from `persona-analyzer.md`.
- The existing `intelligence/personas/{persona}/profile.md`, when one exists.
- The evidence files, for the quotes worth carrying into the profile.
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
claim is tier 3 whatever its origin. Label every inference as an inference in the sentence that makes it.
A seeded assumption the evidence never tested stays marked as an assumption in the final profile; it does
not graduate by surviving.

## Steps

1. **Read the analysis.** Note the supported themes, the emerging ones, the contradictions, and the gaps.
2. **Write the narrative.** Who this person is, what they are trying to achieve, what gets in the way,
   how they decide, and what they will not compromise on.
3. **Rewrite each section from evidence.** Core identity, demographics, psychographics, buying behaviour,
   information habits, sales and marketing signals, product and support needs. Every statement cites the
   evidence file behind it.
4. **Leave demographics and psychographics unfilled where the evidence is silent.** An unevidenced trait
   is the most expensive error this pipeline can make, because everything downstream trusts it.
5. **Carry the contradictions into the profile** rather than resolving them by preference.
6. **Write the team-specific sections** so each is usable without reading the rest: how to approach, what
   to say, what to expect, what to build, how to support.
7. **List the unknowns and the interviews that would close them,** ranked by what each would unblock.
8. **On an update:** preserve the first-created date, set last-updated to today, and add a short list of
   what changed and which evidence changed it.

## Output template

Write to `intelligence/personas/{persona}/profile.md`, one file per role. Use the actual current date and
keep the evidence files where they are.

```markdown
# Persona: {persona}

**First created:** {YYYY-MM-DD}
**Last updated:** {YYYY-MM-DD}
**Evidence items:** {count}, {earliest} to {latest}

## Summary
{Five sentences: who they are, what they want, what blocks them, how they decide, what they reject.}

## Core identity
{Role, organisation type, segment, location - each with its evidence file.}

## Demographics
{Evidenced facts only. Otherwise: "unknown - no evidence".}

## Psychographics
{Motivations, pressures, working style, each with its evidence file, or "unknown - no evidence".}

## Buying behaviour
{Process, criteria, budget authority, timeline, stakeholders, each cited.}

## Information habits
{Channels, content types, trusted sources, each cited.}

## Sales and marketing signals
{Objections with the quote behind each, language that works, proof points that matter.}

## Product and support needs
{Capability priorities, support preferences, onboarding needs, each cited.}

## Contradictions
| Finding | Conflicting finding | Status |
|---|---|---|

## Unknowns and next interviews
| Unknown | Why it matters | Interview or evidence that would settle it |
|---|---|---|

## Evidence summary
- **Supported themes:** {list}
- **Emerging themes:** {list}
- **Assumptions still untested:** {list, kept marked as assumptions}
```

## Evidence ledger

Every material claim in the profile gets one row, carried from the analysis and the evidence files.

| claim | source URL | date | tier |
|---|---|---|---|
| | | | |

## QA gate

The brief fails when any box is unchecked:

- [ ] Every claim in the profile has an evidence-ledger row with a source link and a date.
- [ ] Every inference is labelled as an inference rather than stated as fact.
- [ ] No required section of the output template is empty and no `{placeholder}` is left unresolved.
- [ ] Demographics and psychographics carry evidence or read "unknown - no evidence".
- [ ] Untested seed assumptions are still marked as assumptions, and contradictions are still present.

## Handoff

Next brief: `synthesizer.md`, which reads `intelligence/personas/{persona}/profile.md` alongside the
competitor briefs so the profile it writes speaks to an evidenced buyer.
