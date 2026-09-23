# Positioning scout

## Purpose

Record how one competitor positions itself in its own words: the category it claims, the customer it
targets, the promise it makes, the differentiators it asserts, and the proof it offers.

## Inputs

- `{competitor}` name and the prioritised URLs from `discovery.md`.
- `{company}`, `{product}` and `{audience}` as the skill resolved them.
- Depth: `quick` or `deep`.
- A `{company}` product-context file when one was supplied, used only to frame implications at the end.

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
Confidence follows the tier: High needs two or more sources including at least one tier 1 or tier 2;
Medium needs one strong tier 2 source or several tier 3 sources; everything else is Low.

Most of this brief's raw material is the competitor talking about itself, so expect tier 3. Say so rather
than dressing a self-claim as a fact.

## Steps

1. **Scrape the core messaging pages.** Homepage and main product page always. On a deep run add the
   about page, the solutions pages and two or three customer stories.
2. **Extract the primary message.** Headline and subheadline as exact quotes, the hero value
   proposition, and the above-the-fold calls to action.
3. **Break down the value proposition.** The core promise, the three to five benefits claimed, the proof
   points offered (counts, statistics, awards), and the trust signals shown (logos, certifications).
4. **Read the audience signals.** Who they name, which roles appear in the copy, which pain points they
   address, and which use cases they lead with. Compare against `{audience}`.
5. **List the differentiation claims.** Anything framed as "only", "first" or "unlike". Mark each claim
   substantiated, thin or unsupported based on the proof on the page.
6. **Read the partner and reseller page** when one exists: how they speak to partners versus end
   customers, the programme name and tiers, and any white-label or co-sell messaging.
7. **Deep runs only:** check messaging consistency across pages, note contradictions, and describe brand
   voice - tone, jargon level, and the personality the copy projects.

## Output template

Write to `<intelRoot>/competitors/{competitor}/positioning.md`. Use the actual current date.

```markdown
# Positioning: {competitor}

**Analysis date:** {YYYY-MM-DD}
**Pages analysed:** {urls}

## Core positioning
- **Tagline:** "{exact quote}"
- **Elevator pitch:** {one or two sentences in their framing}
- **Core value proposition:** {the outcome they promise}

## Messaging breakdown
- **Benefits claimed:** {three to five, each with the supporting proof or "none offered"}
- **Primary audience:** {who they clearly target}
- **Secondary audience:** {other segments named}
- **Pain points addressed:** {list}

## Differentiation claims
| Claim | Type | Support |
|---|---|---|
| "{quote}" | only / first / best | substantiated / thin / unsupported |

## Trust and credibility signals
{Customer counts, named logos, awards, certifications, cited statistics.}

## Partner positioning
{How they speak to partners and resellers, programme tiers, white-label messaging, or "no partner
motion found".}

## Positioning scorecard
| Element | Score 1-5 | Note |
|---|---|---|
| Message clarity | | |
| Differentiation | | |
| Credibility of proof | | |
| Fit with {audience} | | |

## Strengths and gaps
- **Strengths:** {what the messaging does well}
- **Gaps:** {where it is vague, unproven or inconsistent}

## Quote library
{Exact quotes worth reusing later, each with its URL.}

### Implications for {company}
{Where {company} {product} can contrast, and where it cannot. Mark each as an inference.}
```

## Evidence ledger

Every material claim in the output gets one row. A claim with no row does not ship.

| claim | source URL | date | tier |
|---|---|---|---|
| | | | |

## QA gate

The brief fails when any box is unchecked:

- [ ] Every claim in the output has an evidence-ledger row with a source URL and a date.
- [ ] Every inference is labelled as an inference rather than stated as fact.
- [ ] No required section of the output template is empty and no `{placeholder}` is left unresolved.
- [ ] Every quote is exact and attributed to the page it came from.
- [ ] Self-claims are marked tier 3 rather than reported as verified capability.

## Handoff

Quick runs: next brief is `synthesizer.md`, which reads
`<intelRoot>/competitors/{competitor}/positioning.md`. Deep runs: next brief is `sales-intel.md`, which
reads the same file for the pricing and partner URLs found here.
