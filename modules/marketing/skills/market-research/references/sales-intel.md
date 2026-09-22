# Sales intelligence scout

## Purpose

Work out how one competitor sells: its pricing and packaging, its conversion path, its partner economics,
and the buying triggers and objections a seller meets in a deal against it.

## Inputs

- `{competitor}` name, plus the pricing, demo and partner URLs from `discovery.md`.
- `{company}`, `{product}` and `{audience}` as the skill resolved them.
- Depth: `quick` or `deep`. This brief runs on deep runs only.
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

Unpublished pricing is the usual case. A price recovered from a review is tier 2 at best and needs a
second mention before it is repeated as a number.

## Steps

1. **Read the pricing page.** Capture the pricing model (per user, per device, flat, usage), the tier
   names and what each includes, published prices, billing terms and discounts, minimum commitments,
   add-ons, and any free tier or trial.
2. **When pricing is not published,** search for prices mentioned in reviews and community threads, and
   record what the page says instead ("contact sales", "custom quote").
3. **Read the sales motion.** Primary and secondary calls to action, whether a buyer can self-serve, the
   form fields demanded, trial length and whether a card is required, and live chat or bot presence.
4. **Read the partner economics** when a partner page exists: margin or wholesale model, volume tiers,
   not-for-resale licensing, partner-only packages, minimum commitments, development funds, deal
   registration, and any signal of conflict with their own direct selling.
5. **Look for competitive content.** Comparison pages, "alternative to" landing pages, feature charts,
   and migration content aimed at switchers.
6. **Read go-to-market signals.** Public job postings and professional-network profiles indicate sales
   team size, geographic spread, and whether there is an outbound motion.
7. **Collect objections and triggers.** From reviews, forums and comparison threads: what makes buyers
   look, what stalls a deal, and which alternatives they weigh.

## Output template

Write to `intelligence/competitors/{competitor}/sales-intel.md`. Use the actual current date.

```markdown
# Sales intelligence: {competitor}

**Analysis date:** {YYYY-MM-DD}
**Pages analysed:** {urls}

## Pricing and packaging
- **Model:** {per user | per device | flat | usage | unpublished}
- **Published prices:** {yes/no, with figures and the page they came from}

| Tier | Price | Included | Notes |
|---|---|---|---|
| | | | |

- **Billing terms:** {monthly, annual, multi-year, minimums}
- **Free tier or trial:** {length, card required, limits}
- **Prices mentioned in reviews:** {figure, source URL, date - or "none found"}

## Sales motion
- **Primary call to action:** {trial | demo | contact sales | buy now}
- **Self-service possible:** {yes/no and what blocks it}
- **Form friction:** {fields demanded}
- **Demo experience:** {what happens after the request}

## Partner economics
{Programme name, margin model, tiers, requirements, benefits, deal registration, conflict signals - or
"no partner motion found".}

## Buying triggers and objections
| Trigger or objection | Evidence | Source | Tier |
|---|---|---|---|
| | | | |

## Alternatives buyers weigh
{Named alternatives that appear in reviews and threads, with how often each appears.}

## Discovery questions
{Five questions a seller can ask that surface the gaps found above without asserting them.}

### Implications for {company}
{Where {company} {product} is priced or packaged differently, and what that changes in a deal. Mark each
as an inference.}
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
- [ ] Every price is either published on a competitor page or corroborated by two independent mentions.
- [ ] Partner terms recovered from gated portals are marked unverified.

## Handoff

Next brief: `voice-of-customer.md`, which reads
`intelligence/competitors/{competitor}/sales-intel.md` for the objections and alternatives to test
against real customer language.
