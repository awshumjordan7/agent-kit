# Evidence collector

## Purpose

Turn raw material - a call, an email, a survey answer, a review, a ticket, or a folder of context files -
into evidence files a persona can be built from. One file per distinct insight.

## Inputs

- `{persona}` name, matching the folder under `intelligence/personas/`.
- The raw material: a single item you are filing by hand, or the paths of context files and folders to
  extract from in bulk. Common text formats are in scope.
- An optional source-type override, and the name or team to record as collector.
- The seeded persona at `intelligence/personas/{persona}/profile.md`, when one exists, so each item can
  be compared to the assumptions already on record.

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
This stage produces the raw material a ledger is later built from, not a ledger: it files single items and
never counts them into a theme. Counting happens in `persona-analyzer.md`.

## Steps

1. **Identify the item.** What was said or observed, which persona it concerns, and the date it was
   collected - the real date, never a date copied from an example.
2. **Determine the source.** Its type (call, email, survey, interview, review, support ticket, sales
   call, meeting, or other), a link or identifier that retrieves it, and who collected it.
3. **Extract verbatim.** Quote directly. A paraphrase loses the language the persona work depends on. Cut
   nothing from the middle of a sentence without marking the cut.
4. **Add the context that makes the quote readable:** the situation, who was involved, the purpose of the
   interaction, and the original date when it differs from the collection date.
5. **Relate it to the persona.** Does it support an assumption on record, contradict one, or add
   something new? Name the assumption.
6. **Note which teams it serves:** sales, marketing, product, support. Skip a team rather than inventing
   relevance.
7. **When extracting in bulk from context files:** read each file, split it into distinct insights, and
   write one evidence file per insight rather than one per source file. Keep the source path and line
   reference as the link.
8. **Check before saving:** real date, correct source type, retrievable link, verbatim snippet, enough
   context, insights stated, persona relationship filled in, file name and location correct.

## Output template

Write to `intelligence/personas/{persona}/evidence/evidence-{YYYY-MM-DD}-{NNN}.md`, sequence numbered
from 001 within a day.

```markdown
# Evidence: {short description}

**Date collected:** {YYYY-MM-DD}
**Source type:** {call | email | survey | interview | review | support ticket | sales call | meeting | other}
**Source link or reference:** {URL, recording link, ticket id, or file path with line reference}
**Collected by:** {name or team}
**Persona:** {persona}
**Theme tags:** {two to four tags, reused across files so themes can be counted later}

## Snippet
{The verbatim quote, observation or data point.}

## Context
{Situation, participants, purpose, original date if different from the collection date.}

## Key insights
- {The one insight this file carries about the persona. A further insight gets its own file.}

## Supports or diverges
{Which recorded assumption this supports or contradicts, or "new - no assumption on record".}

## Team relevance
- **Sales:**
- **Marketing:**
- **Product:**
- **Support:**
```

## Evidence ledger

Not produced here. This stage writes the rows a ledger is later assembled from: each evidence file is one
future row, carrying its source link, date and tier.

| claim | source URL | date | tier |
|---|---|---|---|
| | | | |

## QA gate

The brief fails when any box is unchecked:

- [ ] Every evidence file has a source link or identifier and a real collection date.
- [ ] Every inference drawn in the insights or context is labelled as an inference rather than stated
      as fact.
- [ ] Every snippet is verbatim; paraphrase is marked as paraphrase and any cut is marked.
- [ ] No required section of the output template is empty and no `{placeholder}` is left unresolved.
- [ ] Each file holds one insight, and the file name follows the dated sequence convention.
- [ ] The persona name in the file matches the folder it sits in.

## Handoff

Next brief: `persona-analyzer.md`, which reads every file under
`intelligence/personas/{persona}/evidence/` and counts the themes across them.
