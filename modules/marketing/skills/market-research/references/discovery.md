# Discovery scout

## Purpose

Establish the base facts about one competitor and collect the URLs every later brief works from: the
company, its products, its audience, its pricing signals, and its public proof.

## Inputs

- `{competitor}` name and website. With no competitor named yet, step 0 seeds the list and the rest
  of the brief then runs once per confirmed competitor.
- `{company}`, `{product}` and `{audience}` as the skill resolved them.
- Depth: `quick` or `deep`.
- The existing `intelligence/competitors/{competitor}/discovery.md`, when one exists, so this run records
  what changed rather than restating it.

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

## Steps

0. **Seed the competitor list when none was supplied.** From the business idea, write the category words
   `{audience}` would search, then read those search results, the matching category pages on G2,
   TrustRadius and Capterra, and the "alternatives" pages of the obvious incumbents. Return five to eight
   candidates, each with a name, a website and one line on why it competes with `{company} {product}`,
   ranked by overlap. The ranking is an inference; mark it as one. Hand the list back for confirmation and
   run the steps below only on the competitors that come back confirmed.
1. **Check for a prior run.** Read the existing discovery file if there is one and note its date. Focus
   this run on what has appeared since.
2. **Map the site.** Use the site-mapping tool on the competitor website. Save the URL of the homepage,
   about page, pricing page, product and feature pages, partner or reseller page, careers page, blog or
   resource centre, customer stories, and the demo or contact page.
3. **Find third-party sources.** Search review platforms (G2, TrustRadius, Capterra), category forums,
   professional networks such as LinkedIn, community threads such as Reddit, and trade publications that
   cover `{audience}`. Record one URL per source, not a summary.
4. **Collect company context.** Founding date, headquarters, approximate headcount, funding status, named
   leadership, and the market segments they say they serve. Each fact gets a source.
5. **Note the first impressions.** What the site claims the category is, who it speaks to, and where it
   sits against `{company} {product}`. Mark each as an inference.
6. **Prioritise URLs for later briefs.** Rank the pages the positioning, sales-intelligence,
   voice-of-customer and SEO briefs should read first, highest value at the top.

Deep runs add: job postings from the careers page as a hiring-signal read, and public filings when the
competitor is a listed company. Skip either when the source is unavailable and say so in the output.

## Output template

Write to `intelligence/competitors/{competitor}/discovery.md`. Use the actual current date; never copy a
date from an example.

```markdown
# Discovery: {competitor}

**Analysis date:** {YYYY-MM-DD}
**Website:** {url}
**Competing against:** {company} {product}
**Depth:** {quick|deep}

## Company overview
- Founded:
- Headquarters:
- Approximate headcount:
- Funding status:
- Leadership:

## Key URLs
| Page | URL | Priority |
|---|---|---|
| Homepage | | high |
| Pricing | | high |
| Features | | high |
| Partners | | high |
| About | | medium |
| Careers | | medium |
| Blog | | medium |
| Customer stories | | medium |

## Third-party sources
| Source | URL | Reviews | Rating |
|---|---|---|---|
| | | | |

## First impressions
{Stated category, stated audience, competitive stance. Mark each inference as an inference.}

## URLs for deeper analysis
{Prioritised list handed to the next briefs.}

## Source availability
| Source or method | Used / fallback / unavailable | Note |
|---|---|---|
| | | |

### Implications for {company}
{What these base facts change about where {company} {product} sits against this competitor, and which of
them the later briefs should test first. Mark each as an inference.}
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
- [ ] Every tier 1 or tier 2 claim carries a dated link; uncorroborated claims are marked tier 3.
- [ ] Dates are the date the source was accessed, not a date copied from an example.

## Handoff

Next brief: `positioning.md`, which reads `intelligence/competitors/{competitor}/discovery.md` for the
prioritised URL list. On a deep run the same file also seeds `sales-intel.md`, `voice-of-customer.md`,
`seo-content.md` and `internal-sources.md`.
