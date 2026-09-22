# Marketing

Disabled by default and depends on Firecrawl. Adds source-backed market research and a human-reviewed
content pipeline. It does not require an additional API key.

The research method is the same in every brief. Each claim is graded into one of three tiers: a direct
primary source, a corroborated secondary source, or a single uncorroborated or inferred claim. A claim
reaches the first two tiers only with a dated link. Every material claim gets a row in an evidence ledger
carrying its source, date and tier. Each brief ends in a QA gate that fails the work when a claim has no
source, an inference is unlabelled, or a required section of the output template is empty.

Two skills use it. `market-research` starts from a business idea in plain words, derives the company,
product, audience and first competitor list, confirms them in one question, then runs eleven briefs -
seven on the competitor track and four on the persona track - as `sonnet` scouts, one brief each. A
`quick` run uses discovery, positioning and the synthesizer; a `deep` run adds sales intelligence,
customer language, SEO, internal sources when access exists, and the persona track.
`content-pipeline` collects source material, renders a draft in one of four modes - launch messaging,
blog draft, release communication, messaging framework - checks the draft against the source, takes a
human edit, and publishes only after approval.
