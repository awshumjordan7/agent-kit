# Internal sources scout

## Purpose

Find what `{company}`'s own conversations already say about one competitor. Call recordings, meeting
notes, support tickets and sales notes hold first-hand customer language that no public source carries.

## Inputs

- `{competitor}` name and the alternatives it is confused with.
- Access to whatever `{internal transcript tool}` the team uses: call recordings, meeting notes, a
  ticket system, a customer feedback store, or a shared notes folder.
- `{company}`, `{product}` and `{audience}` as the skill resolved them.
- Depth: `quick` or `deep`. This brief runs on deep runs only, and only when access exists.

## Evidence and confidence

Grade every claim before it enters the output:

- **Tier 1 - direct primary source.** First-hand material: an interview, a call transcript, a support
  ticket, a survey response, or a signed statement from the party the claim is about.
- **Tier 2 - corroborated secondary source.** An independent third party confirmed by a second
  independent source: review platforms, trade coverage, analyst write-ups, distributor listings.
- **Tier 3 - single uncorroborated or inferred.** One unconfirmed mention, a vendor self-claim, or your
  own reasoning from other facts.

Corroboration rule: a claim reaches tier 1 or tier 2 only with a dated link. Without a dated link the
claim is tier 3 whatever its origin. Internal material is tier 1 only when the record itself is linkable
and dated; a remembered conversation with no record is tier 3. Label every inference as an inference in
the sentence that makes it. Confidence follows the tier: High needs two or more sources including at
least one tier 1 or tier 2; Medium needs one strong tier 2 source or several tier 3 sources; everything
else is Low.

## Steps

1. **Set the date window.** With no prior internal-sources file, search everything available. With one,
   search from its date forward and say which window you used.
2. **Build name variations.** The exact name, spaced and joined forms, common abbreviations, the category
   suffix people attach, transcription mis-hearings and homophones, and any former brand name. Search
   each variation separately, then deduplicate by record id.
3. **Search whatever internal tool exists** for those variations. Use that tool's own interface; this
   brief holds no query syntax, because the tool differs per team. Record for each hit the record id, the
   date, the speaker role, and a link back to the moment.
4. **Verification gate.** A mention counts as evidence only when the record has an id, a date and a
   retrievable link, and the quote is read in context rather than taken from a search snippet. Mentions
   that fail this gate are listed separately as unverified and never feed a conclusion.
5. **Tag every verified mention by theme:** pricing, capability comparison, switching consideration,
   current-customer experience, sales objection, onboarding or support issue, market perception.
6. **Read the themes.** Per theme: the recurring point, the strongest quote, the sentiment, the number of
   distinct records, and which customer segments it came from.
7. **Cross-check against public evidence.** Where internal and public findings agree, confidence rises.
   Where they disagree, record the contradiction rather than picking the flattering side.
8. **Roll every verified mention into the evidence ledger**, graded by how direct the record is rather
   than by having passed the gate. A customer speaking for themselves on a linked, dated record is
   tier 1. A colleague's note reporting what a customer said is second-hand: tier 2 when a second
   independent record confirms it, tier 3 on its own.
9. **Record a zero result explicitly** when the search finds nothing, and lower the confidence of every
   claim that would have rested on it.

## Output template

Write to `intelligence/competitors/{competitor}/internal-sources.md`. Use the actual current date. Treat
the contents as internal: it holds customer conversations.

```markdown
# Internal sources: {competitor}

**Analysis date:** {YYYY-MM-DD}
**Tool searched:** {internal transcript tool}
**Date window:** {all time | from YYYY-MM-DD} and why
**Name variations searched:** {list}

## Search summary
| Variation | Records found | Verified | Unverified |
|---|---|---|---|
| | | | |

## Mentions by theme
### {Theme}
- **Point:** {what is being said}
- **Quote:** "{verbatim}" - {role}, {date}
- **Record:** {link}
- **Distinct records:** {count}
- **Sentiment:** {positive | negative | neutral | mixed}

## Cross-check against public evidence
| Internal finding | Public finding | Agreement |
|---|---|---|
| | | agrees / contradicts / untested |

## Unverified mentions
{Mentions that failed the verification gate, kept out of the conclusions.}

## Source links
{Every record link cited above, with its date and a one-line context.}

### Implications for {company}
{What the conversations change about how {company} {product} is positioned or sold. Mark each as an
inference.}
```

## Evidence ledger

Every material claim in the output gets one row. A claim with no row does not ship.

| claim | source URL | date | tier |
|---|---|---|---|
| | | | |

## QA gate

The brief fails when any box is unchecked:

- [ ] Every claim in the output has an evidence-ledger row with a source link and a date.
- [ ] Every inference is labelled as an inference rather than stated as fact.
- [ ] No required section of the output template is empty and no `{placeholder}` is left unresolved.
- [ ] Every mention used as evidence passed the verification gate; the rest sit under unverified.
- [ ] A zero-result search is stated as a zero result rather than left implicit.

## Handoff

Next brief: `synthesizer.md`, which reads
`intelligence/competitors/{competitor}/internal-sources.md` and carries each verified mention at the
tier this brief graded it.
