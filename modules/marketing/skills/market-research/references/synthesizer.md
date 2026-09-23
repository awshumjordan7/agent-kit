# Research synthesizer

## Purpose

Merge the competitor briefs into one profile: comparison tables, the findings that hold up, the evidence
behind them, the contradictions, and the questions still open.

## Inputs

- Every brief written for this competitor under `<intelRoot>/competitors/{competitor}/`.
- `{company}`, `{product}` and `{audience}` as the skill resolved them.
- `<intelRoot>/personas/{persona}/profile.md` on a deep run where the persona track also ran.
- Depth: `quick` or `deep`.
- A `{company}` product-context file when one was supplied.

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

Hard rule for this brief: anything written as a counter-argument or a recommended response must be
Medium confidence or better, or it ships marked "needs validation".

## Steps

0. **Load `{company}`'s own product context when a file is supplied; otherwise skip.** Use it only where
   the profile compares the competitor to `{company} {product}`, and never invent a capability the file
   does not state.
1. **Check the inputs are current.** Read the analysis date in every brief for this competitor. A brief
   older than this run, or one whose QA gate failed, is sent back before synthesis starts.
2. **Read everything and mark the overlaps.** Themes that appear in two or more briefs, contradictions
   between them, the strongest single finding per area, and the gaps nobody covered.
3. **Write the story.** Who they are, what bet they are making, where they win, where they are exposed.
4. **Build the comparison tables.** Positioning, pricing and packaging, customer sentiment, and content
   presence, each row carrying its confidence label.
5. **Separate facts from inferences from unknowns.** Three explicit lists. An unknown stays an unknown;
   it does not become a cautious guess.
6. **Draft the actionable output.** For marketing: positioning guidance and content openings. For sales:
   objections heard and the evidence behind each. For product: capability gaps that customers name.
7. **Stop and return the work** when any upstream QA gate failed, any required brief is missing, a
   recommendation rests only on tier 3 evidence, or unresolved `{placeholder}` text remains. Say what is
   missing instead of synthesizing around it.

## Output template

Write to `<intelRoot>/competitors/{competitor}/profile.md`. Quick profiles carry the summary, the
positioning and pricing tables, the top three strengths and weaknesses, and the sources. Deep profiles
carry every section below.

```markdown
# Competitor profile: {competitor}

**First analysed:** {YYYY-MM-DD}
**Last updated:** {YYYY-MM-DD}
**Depth:** {quick|deep}
**Briefs used:** {list, each with its analysis date}

## Executive summary
{Five sentences: who they are, who they sell to, how they win, where they are exposed, what to watch.}

## Comparison tables
| Dimension | {competitor} | {company} {product} | Confidence |
|---|---|---|---|
| Category claimed | | | |
| Primary audience | | | |
| Pricing model | | | |
| Strongest proof | | | |

## Facts
{Claims with tier 1 or tier 2 evidence, each with its source and date.}

## Inferences
{Reasoned conclusions, each labelled as an inference with the facts it rests on.}

## Unknowns
{What the research could not establish, and the source that would settle it.}

## Contradictions
| Claim | Source A | Source B | Status |
|---|---|---|---|

## Open questions
{The questions worth the next round of research, most valuable first.}

### Implications for {company}
{Where {company} {product} contrasts, where it does not, and which of these need validation before
use.}
```

## Evidence ledger

Every material claim in the profile gets one row, carried forward from the briefs it came from.

| claim | source URL | date | tier |
|---|---|---|---|
| | | | |

## QA gate

The brief fails when any box is unchecked:

- [ ] Every claim in the profile has an evidence-ledger row with a source URL and a date.
- [ ] Every inference sits under Inferences, labelled, never mixed into Facts.
- [ ] No required section of the output template is empty and no `{placeholder}` is left unresolved.
- [ ] Every upstream brief passed its own QA gate and carries this run's date.
- [ ] No recommendation rests on tier 3 evidence alone without a "needs validation" marker.

## Handoff

Next brief: `content-pipeline/references/modes.md`, which reads
`<intelRoot>/competitors/{competitor}/profile.md` at the render stage of the `content-pipeline` skill.
This is the last brief in the market-research competitor track.
