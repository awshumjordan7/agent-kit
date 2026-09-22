# Voice-of-customer scout

## Purpose

Collect what customers say about one competitor in their own words, and compare that record against what
the competitor's marketing promises.

## Inputs

- `{competitor}` name and the review-site and community URLs from `discovery.md`.
- The claims list from `positioning.md`, used for the promise-versus-reality comparison.
- `{company}`, `{product}` and `{audience}` as the skill resolved them.
- Depth: `quick` or `deep`. This brief runs on deep runs only.

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

A theme needs three independent reviews before it is reported as a pattern. One loud review is one review.

## Steps

1. **Read the review platforms** (G2, TrustRadius, Capterra) at minimum. Capture the rating, the review
   count, the category placements, the recurring pros, the recurring cons, and dated quotes.
2. **Sort the feedback into themes.** Positive themes: capability, ease of use, support, value,
   onboarding, reliability, integrations. Negative themes: missing capability, defects, support delays,
   price complaints, usability, migration pain, contract and cancellation friction.
3. **Read the communities:** community forums (Reddit) and professional networks (LinkedIn). These carry
   the unfiltered version. When a site blocks scraping, work from search results and say in the output
   that the material came from search snippets.
4. **Pull switching evidence.** Who reviewers compared the competitor to, what made them leave, and what
   made them choose it.
5. **Compare promise with reality.** Take each claim from `positioning.md` and find the customer evidence
   that supports or contradicts it. Record both directions.
6. **Deep runs add** a time comparison - are recent reviews better or worse than older ones - and a
   segment comparison across company sizes and, where visible, `{audience}` versus other buyers.

## Output template

Write to `<intelRoot>/competitors/{competitor}/voice-of-customer.md`. Use the actual current date. Quote
customers exactly; never tidy a quotation.

```markdown
# Voice of customer: {competitor}

**Analysis date:** {YYYY-MM-DD}
**Sources analysed:** {platforms and URLs}

## Ratings overview
| Platform | Rating | Reviews | Date read |
|---|---|---|---|
| | | | |

## What customers praise
| Theme | Supporting reviews | Representative quote | Tier |
|---|---|---|---|
| | | | |

## What customers complain about
| Theme | Supporting reviews | Representative quote | Tier |
|---|---|---|---|
| | | | |

## Dealbreakers
{Complaints that appear as the stated reason for leaving.}

## Community sentiment
{Forum, discussion-site and professional-network findings, with thread URLs and how the material was
retrieved.}

## Switching patterns
- **Compared against:** {named alternatives and frequency}
- **Why customers left:** {triggers}
- **Why customers chose them:** {triggers}

## Promise versus reality
| Marketing claim | Customer evidence | Verdict |
|---|---|---|
| | | supported / contradicted / untested |

## Support and onboarding perception
{What reviewers say about response times, quality, and the first ninety days.}

## Quote library
{Exact quotations with platform, date and URL, kept verbatim.}

### Implications for {company}
{Where the gaps are addressable by {company} {product} and where they are not. Mark each as an
inference.}
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
- [ ] Every quotation is verbatim and carries its platform, date and URL.
- [ ] No theme is reported as a pattern on fewer than three independent reviews.

## Handoff

Next brief: `seo-content.md`, which reads
`<intelRoot>/competitors/{competitor}/voice-of-customer.md` for the customer language to check against
the competitor's published content.
