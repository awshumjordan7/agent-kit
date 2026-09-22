# Persona analysis scout

## Purpose

Read every evidence file for one persona and report what the evidence actually shows: the themes that
recur, the assumptions it contradicts, the quality of the material, and where it runs out.

## Inputs

- Every file under `<intelRoot>/personas/{persona}/evidence/`.
- The persona at `<intelRoot>/personas/{persona}/profile.md`, when one exists, for the assumptions to
  test against.
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
Theme strength is a count, not a judgement. The unit is one insight section (`E{k}`) of an evidence file:
three or more insights make a supported theme, one or two make an emerging theme, and a single insight
never makes a persona trait.

## Steps

1. **Inventory the evidence.** Read every file. Record the count of files and insights, the date range,
   the source-type spread, and any file that is incomplete or unreadable.
2. **Extract themes.** Group similar snippets, name the recurring point, and count the distinct insights
   behind each. Keep supported and emerging themes apart.
3. **Map each theme to a persona section:** core identity, demographics, psychographics, buying
   behaviour, information habits, sales and marketing signals, product and support needs.
4. **Compare with the seeded persona.** For each assumption on record: supported, contradicted, or
   untested. Name the insight (`file#E{k}`) on both sides.
5. **Record contradictions in full** - which insights conflict, how strong each side is, and what evidence
   would resolve it. Never average two contradictory findings into one bland claim.
6. **Pull the team-specific reads:** objections and decision patterns for sales, resonant and failed
   language for marketing, capability priorities and gaps for product, and onboarding and support needs.
7. **Grade the material.** High: verbatim quote, clear context, retrievable source. Medium: specific but
   paraphrased. Low: vague, thin context, or an unclear source. Report the mix, not an average.
8. **Name the gaps.** Which sections the evidence cannot yet support, and what kind of evidence would.

## Output template

Write to `<intelRoot>/personas/{persona}/analysis.md`. Use the actual current date.

```markdown
# Evidence analysis: {persona}

**Analysis date:** {YYYY-MM-DD}
**Evidence files:** {count}
**Insights:** {count}
**Date range:** {earliest} to {latest}

## Evidence inventory
| Insight (file#E{k}) | Date | Source type | Quality |
|---|---|---|---|
| | | | |

## Supported themes (three or more insights)
| Theme | Insights | Representative quote | Persona section |
|---|---|---|---|
| | | | |

## Emerging themes (one or two insights)
| Theme | Insights | Quote | Persona section |
|---|---|---|---|
| | | | |

## Against the seeded persona
| Assumption | Evidence finding | Status |
|---|---|---|
| | | supported / contradicted / untested |

## Contradictions
| Contradiction | File A | File B | What would resolve it |
|---|---|---|---|
| | | | |

## Team-specific findings
- **Sales:** {objections, decision patterns, language that works}
- **Marketing:** {messages that land, messages that fail, channels}
- **Product:** {capability priorities, gaps, adoption friction}
- **Support:** {onboarding needs, recurring issues, what good looks like}

## Evidence quality
| Quality | Insights | Note |
|---|---|---|
| High | | |
| Medium | | |
| Low | | |

## Gaps
{Sections the evidence cannot support yet, and the evidence that would close each gap.}
```

## Evidence ledger

Every material claim in the analysis gets one row, carried from the insight it came from.

| claim | source URL | date | tier |
|---|---|---|---|
| | | | |

## QA gate

The brief fails when any box is unchecked:

- [ ] Every claim in the analysis has an evidence-ledger row with a source link and a date.
- [ ] Every inference is labelled as an inference rather than stated as fact.
- [ ] No required section of the output template is empty and no `{placeholder}` is left unresolved.
- [ ] No theme is reported as supported on fewer than three distinct insights.
- [ ] Every contradiction is recorded rather than smoothed away.

## Handoff

Next brief: `persona-synthesizer.md`, which reads `<intelRoot>/personas/{persona}/analysis.md` and
rewrites the persona from the supported themes.
