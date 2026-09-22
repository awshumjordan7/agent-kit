---
name: market-research
description: Research a company, product, market, competitors, or customer personas with cited evidence.
---

# Market research

The entry point is a business idea in plain words - a product, a company, a service, or a market someone
wants to enter. One sentence or one paragraph is enough.

From that idea, derive `{company}`, `{product}`, `{audience}` and a first list of competitors, then
confirm all four in a single question before the per-competitor research starts. When no competitors are
named, run the seeding pass in `references/discovery.md` first and put its candidates into that same
question. Optional inputs: named competitors, `quick` or `deep` (default `quick`), a `{company}`
product-context file, and access to an internal transcript or call-notes tool.

Create a run directory and write findings under `intelligence/competitors/<name>/` and
`intelligence/personas/<name>/`.

## Briefs

Competitor track:

| Brief | Runs on | Produces |
|---|---|---|
| `references/discovery.md` | quick, deep | base facts and the URL list every later brief reads |
| `references/positioning.md` | quick, deep | category, audience, promise, differentiators, proof |
| `references/sales-intel.md` | deep | pricing, packaging, sales motion, partner economics, objections |
| `references/voice-of-customer.md` | deep | customer language, themes, switching triggers |
| `references/seo-content.md` | deep | content themes, search intent, lead capture, gaps |
| `references/internal-sources.md` | deep, when internal access exists | verified mentions from internal conversations |
| `references/synthesizer.md` | quick, deep | the competitor profile |

Persona track (deep runs):

| Brief | Produces |
|---|---|
| `references/persona-seeder.md` | the first persona, with every belief marked as an assumption |
| `references/evidence-collector.md` | one evidence file per insight, from raw material or context files |
| `references/persona-analyzer.md` | counted themes, contradictions, evidence quality, gaps |
| `references/persona-synthesizer.md` | the evidenced persona, with unknowns and next interviews |

## Running it

Use scouts with `model: sonnet`. Give each scout one brief and the shared inputs; never two briefs at
once. Run the competitor track in the order of the table, and the persona track in its own order.

Every brief carries the same three evidence tiers, the same ledger table, and a QA gate that fails the
brief when a claim has no source, an inference is unlabelled, or a required section is empty. A brief
that fails its gate is re-run before the synthesizer reads it.

The synthesizer combines evidence into short tables. It must separate facts, inferences, and unknowns.
