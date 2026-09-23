# SEO and content scout

## Purpose

Map one competitor's published content: the topics it owns, the search intent it targets, how it captures
leads, and the gaps `{company}` could fill.

## Inputs

- `{competitor}` name and the blog, resource and content URLs from `discovery.md`.
- The customer language collected in `voice-of-customer.md`, used to test whether their content answers
  the questions buyers actually ask.
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

Search volume and ranking estimates are inferences unless they come from a tool this run actually used.
Never present an estimated volume as a measured one.

## Steps

1. **Map the content hub.** Use the site-mapping tool, or `firecrawl_search` + `firecrawl_scrape` when no
   map tool exists, on the blog and resource paths. Record the category structure, the content types
   offered, and the split between gated and open material.
2. **Read the keyword signals without paid tools.** Indexed pages via a `site:` search, page titles, the
   homepage title tag and meta description, heading structure, and the phrases the copy repeats.
3. **Classify the content by theme and goal.** Count pieces per theme and name the business goal each
   theme serves: awareness, search, authority, proof, engagement, competitive, partnerships.
4. **Name the content pillars.** The three to five topics they publish most, and whether those match the
   positioning recorded in `positioning.md`.
5. **Read the lead-capture strategy.** What sits behind a form, what is offered for an email address, and
   how aggressive the capture is.
6. **Assess digital presence.** Followers and posting rhythm on the professional and social networks they
   use, and public coverage that links to them.
7. **Find the gaps.** Questions from `voice-of-customer.md` their content never answers, thin or outdated
   pieces, and formats they do not produce.
8. **Deep runs add** a close read of three to five high-value pieces: depth, internal linking, call to
   action placement, and production quality.

## Output template

Write to `<intelRoot>/competitors/{competitor}/seo-content.md`. Use the actual current date.

```markdown
# SEO and content: {competitor}

**Analysis date:** {YYYY-MM-DD}
**Content URLs analysed:** {urls}

## Content hub
- **Structure:** {categories, tags, paths}
- **Publishing rhythm:** {posts per month, most recent date}
- **Content types:** {articles, guides, webinars, tools, studies}
- **Gated versus open:** {split}

## Apparent keyword targets
| Keyword or phrase | Where it appears | Evidence | Tier |
|---|---|---|---|
| | | | |

## Content themes
| Theme | Pieces | Example title | Business goal |
|---|---|---|---|
| | | | |

## Content pillars
{Three to five topics, and whether each matches their stated positioning.}

## Lead capture
{Gated assets, form depth, email capture tactics, nurture signals.}

## Digital presence
| Network | Followers | Posting rhythm | Note |
|---|---|---|---|
| | | | |

## Quality assessment
- **Strengths:** {what their content does well}
- **Weaknesses:** {thin, outdated or unsupported material}

## Gaps
- **Questions buyers ask that they never answer:** {from voice-of-customer evidence, with the review URL}
- **Formats they do not produce:** {list}
- **Topics they cover poorly:** {list}

### Implications for {company}
{Content {company} could publish first or better, ranked by the evidence behind the gap. Mark each as an
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
- [ ] No search volume, traffic figure or ranking is presented as measured unless a tool produced it.
- [ ] Every gap is tied to a customer question with a source, not to a hunch.

## Handoff

Next brief: `internal-sources.md` when internal access exists, otherwise `synthesizer.md`. Both read
`<intelRoot>/competitors/{competitor}/seo-content.md`.
