# Content modes

Four output shapes for the render stage. Pick one from the request; when the request is ambiguous, name
the four and ask which. Every claim in a draft traces back to collected source material, and
`scripts/check_fidelity.py` checks that the links and code in the source survived into the draft.

Placeholders: `{company}`, `{product}`, `{audience}`, `{competitor}`, `{feature}`.

## Mode 1: Launch messaging

### Purpose

Give a launch its headlines, value propositions, feature description, subject lines and calls to action,
each grounded in a source rather than invented.

### Inputs

- `{feature}` or initiative name, and `{product}`.
- `{audience}`, or the persona profiles to derive it from.
- The specification or change record the feature comes from - the factual source for what it does.
- Persona profiles for the pain points, decision criteria and trust signals.
- One to three competitor profiles for the differentiation angles.

### Template

```markdown
# Launch messaging: {feature}

> **Product:** {company} {product}
> **Generated:** {YYYY-MM-DD}
> **Sources:** {every file read}

## Headlines (three options)
1. {benefit-led, 8-12 words}
2. {problem-led, 8-12 words}
3. {differentiation-led, 8-12 words}

## Subheadlines (three options)
1. {expands headline 1, 15-25 words}
2. {expands headline 2}
3. {expands headline 3}

## Value propositions
### 1. {title}
{Two or three sentences.}
- **Evidence:** {the specification section, persona pain point or competitive gap behind it}
- **Resonance:** {which persona this speaks to, and why}

### 2. {title}
{As above, with its own evidence and resonance lines.}

### 3. {title}
{As above.}

## Customer-facing description
<!-- Exactly 100 words. Benefits over features: "this lets you", not "we added". -->
{100 words}

## Email subject lines (five options)
1. {curiosity} 2. {benefit} 3. {timeliness} 4. {question} 5. {announcement}

## Calls to action (three)
1. {text} - best for: {context}
2. {text} - best for: {context}
3. {text} - best for: {context}

## Competitive differentiation
- vs {competitor}: {statement} (source: {competitor profile section})

## Do and do not
| Say | Do not say | Why |
|---|---|---|
| {phrasing} | {phrasing} | {reason} |
```

## Mode 2: Blog draft

### Purpose

Produce a publishable draft on one topic - problem, solution, benefits, getting started - written for
`{audience}` and sourced throughout.

### Inputs

- `{feature}` or topic, and `{product}`.
- `{audience}`, defaulting to the primary persona for the product.
- Tone, defaulting to professional and direct.
- The specification or change record, the recent release notes, the persona profile, and one or two
  competitor profiles.

### Template

```markdown
# {title, primary keyword used naturally}

> **Product:** {company} {product}
> **Generated:** {YYYY-MM-DD}
> **Audience:** {persona}
> **Word count target:** 800-1200
> **Primary keyword:** {keyword}
> **Sources:** {every file read}

## Meta
- **SEO title:** {60 characters}
- **Meta description:** {155 characters}
- **Slug:** /blog/{slug}
- **Category:** {product update | industry insight | practice | how-to}

{Intro hook: two or three sentences naming the problem, addressed to the reader.}

## The problem
{Three or four paragraphs grounded in persona evidence, with one concrete scenario.}

## The solution
{Three or four paragraphs. "You can now" and "which means" framing, no internal jargon.}

## Key benefits
{Three to five items: one sentence on what it is, one on why it matters to {audience}.}

## How it works
{A short practical walkthrough.}

## What it means for your business
{One or two paragraphs tying back to the wider trend and the reader's economics.}

## Conclusion and call to action
{Two or three sentences, one clear next step.}

## Internal notes (not for publication)
- **Competitive angle:** {which weakness this addresses}
- **Persona alignment:** {which insights shaped the tone}
- **Distribution:** {channels}
- **Related content:** {links}
```

## Mode 3: Release communication

### Purpose

Turn one release into customer-facing communication, filtered to what is actually public.

### Inputs

- `{product}` and the release period.
- The public release notes for that period - the source of truth for customer-facing wording.
- The internal notes for context only; nothing internal reaches the output.
- The early-access opt-in text and link, when the release includes early-access items.
- Channel, defaulting to email.

### Template

```markdown
# Release communication: {company} {product} - {period}

> **Generated:** {YYYY-MM-DD}
> **Source:** {path to the public release notes}
> **Visibility filter:** public and early-access items only

## Email

### Subject line
{Benefit-led, 6-10 words, names the product.}

### Preview text
{40-90 characters, complements the subject.}

### Body
{One opening sentence acknowledging the release.}

**What's new**
- **{item}** - {one or two sentences, "you can now" framing}

**Early access**
- **{item}** - {one or two sentences}
> {opt-in text}
> {opt-in link}

**What this means for you**
{Two or three sentences on the release as a whole.}

{Call to action.}

## Channel variations

### Short message (chat)
{Two or three sentences plus a link, informal.}

### Social post
{Three to five sentences, professional, one or two relevant tags.}
```

## Mode 4: Messaging framework

### Purpose

Set the positioning of `{company} {product}` against one competitor, with the proof points, the channel
variations and the responses to their common claims.

### Inputs

- `{product}` and `{competitor}`.
- The persona profile for the buyer: what they care about, how they decide, which language lands.
- The competitor profile: positioning, strengths, weaknesses, pricing, customer sentiment.
- Campaign context, when there is one.

### Template

```markdown
# Messaging framework: {company} {product} vs {competitor}

> **Generated:** {YYYY-MM-DD}
> **Buyer:** {persona}
> **Sources:** {every file read}

## Positioning statement
**For** {audience}
**Who** {pain point from the persona profile}
**{company} {product} is** {category}
**That** {key benefit}
**Unlike** {competitor}, **it** {primary differentiator}
**Because** {reason to believe}

## Proof points
1. **{title}** - claim: {assertion} / evidence: {source} / their gap: {what they cannot match}
2. **{title}** - claim: {assertion} / evidence: {source} / their gap: {gap}
3. **{title}** - claim: {assertion} / evidence: {source} / their gap: {gap}

## Do and do not
| Do | Do not | Rationale |
|---|---|---|
| {approach} | {approach} | {grounded in persona or competitive evidence} |

## Channel variations
### Landing page
**Headline:** {headline}
**Subheadline:** {subheadline}
**Body (50-75 words):** {copy}
**Call to action:** {text}

### Email
**Subject:** {line} / **Preview:** {text}
**Hook:** {one or two sentences}
**Key message:** {two or three sentences}
**Call to action:** {text}

### Sales deck notes
**Slide title:** {title}
**What to say:** {two or three sentences}
**Proof to show:** {evidence}

### Social post
**Post (100-150 words):** {text}
**Tags:** {three to five}

## Response playbook
### If {competitor} says "{claim}"
**Response:** "{counter}"
**Evidence:** {source}

## Internal notes
- **Persona insights used:** {sections}
- **Competitor profile freshness:** {its last-updated date}
- **Review cadence:** refresh when the competitor profile or the persona changes
```
