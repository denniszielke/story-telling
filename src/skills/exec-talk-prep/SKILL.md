---
name: exec-talk-prep
description: |
  Prepares technically-grounded executive presentations (typically 45 minutes) through a
  four-phase workflow: (1) talking points & messages, (2) abstract, (3) narrative, (4) slides.
  Built for senior technical speakers positioning Microsoft platform relevance, thought
  leadership, and collaboration around themes like contextual intelligence, agentic platforms,
  AI-harness-driven software engineering, multi-agent ecosystems, and human-AI collaboration.
  Use when the user asks to "prepare a talk", "prep my exec presentation", "build a keynote",
  "write a session abstract", "structure my talk narrative", "validate my talking points",
  "create a speaker flow", "expand my abstract", or "help me design conference slides".
  Each phase can run standalone or in sequence. Do NOT use for internal status decks, routine
  business reviews, or non-presentation documents (use docx/pptx directly for those).
  cowork:
    category: writing
    icon: SlideText
---

# Executive Talk Prep

Reproducible workflow for preparing technically-grounded executive presentations. The speaker
brings 3-4 topics aligned to 3-4 messages they want to land; this skill validates, sequences,
grounds, and packages them into a deliverable talk.

The four phases are independent — the user may invoke any one ("just the abstract", "redo the
narrative"). When the user says "prepare my talk" with no phase named, run them in order,
pausing for approval between each. Always confirm which phase(s) before diving in.

## The Throughline Method

The talks this skill produces work because every topic hangs off ONE umbrella thesis, and each
topic is positioned as an *enabler of* or *reason for failure of* an exciting headline trend
(e.g. "agentic AI succeeds or fails on the foundation underneath it: platform, modernization,
skills, operations"). Find that umbrella in Phase 1 and carry it through all four phases. Each
topic section follows the same internal rhythm:

**Trend + anchor stat → Microsoft observation → offer / engagement model → recommendation → one-line story arc.**

Keep the focus on *impact* — how Microsoft assets, products, partnerships, and learnings change
the customer's outcome — not on product feature lists.

## Phase 1 — Talking Points & Messages

Goal: validated talking points, in full sentences, each tagged with its message, audience
relevance, and key phrases to land — sequenced so concepts build on each other and fit the slot.

**Gather context FIRST. Ask before drafting** (one or two focused questions at a time, not a wall):
- **Audience**: role/seniority, technical depth, what they already know, what they care about
- **Setting**: time slot (default 45 min), format (keynote/breakout), who owns the agenda
- **Topics & messages**: the 3-4 topics and the 3-4 messages to land (map one to one)
- **Microsoft angle**: which technical capabilities, engagement models, or ecosystem
  partnerships back each topic
- **Constraints**: themes to emphasize/avoid, any customer or NDA sensitivities

Then:
1. Propose the umbrella thesis and the topic sequence (concepts must build on each other).
2. For each topic, write the talking point in **full sentences** with: the message it lands,
   why it's relevant to *this* audience, and 2-3 key phrases the speaker should actually say.
3. Pressure-test: does each concept depend on the prior one? Is the technical depth right for
   the audience? Does the whole thing fit the time slot? Flag anything that doesn't.
4. Use research tools to validate claims (see **Research & Grounding**).

Output the talking points as structured prose the speaker can read aloud and react to.

## Phase 2 — Abstract

Goal: an abstract (**≤500 words**) to hand the agenda owner that excites the audience AND lets
them self-select as the right target group.

- Open with the tension or trend that makes the topic urgent.
- Name the 3-4 topics so a reader can see the substance, not just hype.
- Use language that signals the technical level so the wrong audience opts out and the right one
  leans in.
- Close on the payoff (what they'll leave with). Keep it tight and exciting.
- Reflect the umbrella thesis from Phase 1. If Phase 1 wasn't run, ask for the topics/messages.

## Phase 3 — Narrative

Goal: expand the abstract into a speaker flow (typically ~2 pages for a 45-min slot) that
validates pacing and exposes inconsistencies in how technical concepts are introduced.

- Write it as a flowing speaker narrative (offer first-person voice if the speaker is named).
- Apply the **Throughline Method** rhythm to every topic section.
- Add **bracketed timing cues** per section (e.g. `[Trend 2 — ~9 min]`) that sum to the slot.
- For each section recommend, where relevant: a **customer story**, an **industry example**, a
  **market trend / stat**, and a **Microsoft-specific learning**. Pull real ones via research
  tools — do not invent customer names or outcomes.
- Sequence so technical depth ramps smoothly; flag any jump where a concept is used before it's
  introduced.
- End on the collaboration / Customer Success payoff.
- After writing, give a short **flow check**: note any pacing risk, depth inconsistency, or topic
  that's carrying too much/too little time.

## Phase 4 — Slides

Goal: a story-driven deck with *just enough* detail — pictures over text — that the speaker can
pace freely.

- Prefer visuals; minimize text per slide. One idea per slide.
- The user often has **pre-generated images to modify** — ask for them first. Adapt visuals to
  the **customer, the technical concept, or the industry** being addressed.
- For new visuals: use `search_images` for real imagery; generate diagrams/schematics with
  Python (matplotlib/PIL) per the image-generation rules; convert SVG icons as needed.
- **Avoid obvious statements.** Every slide must add something new, current, and relevant — no
  filler "Agenda" or "Why AI matters" platitudes.
- Map slides to the Phase 3 sections so timing carries over. Note suggested dwell time per slide.
- Invoke the **pptx** skill to build the deck; save to `output/`. Keep speaker notes as the
  narrative text so the deck and script stay in sync.

## Research & Grounding

Use tools actively — never assert market facts from memory:
- **`deep-research-agent`** (preferred for stats): grounded statistics with citations for trends,
  benchmarks, and quotes. Brief it with the specific themes; ask it to label each figure by
  source and flag confidence/vintage.
- **`web_search`**: current market trends, competitor moves, recent reports.
- **`SearchM365`**: the speaker's own emails, files, Teams, and notes for prior decks, customer
  context, and internal learnings.
- **`search_images`**: visual assets for slides.

**Source discipline:** distinguish stats from the speaker's provided/authoritative reports vs.
supplementary sources. Flag any figure that is older, from a press release/snippet, or
lower-confidence — call it out so the speaker isn't caught out on stage. Never fabricate
customer names, numbers, quotes, or outcomes; use a clearly-marked placeholder instead.

## Guardrails

- **Context before content**: in Phase 1, ask for audience/topic/time context before drafting.
- **One umbrella, carried throughout**: all four phases must reflect the same thesis.
- **Impact over features**: position Microsoft capabilities, engagement models, and partnerships
  by the outcome they create, not by feature enumeration.
- **Stay current and non-obvious**: prefer fresh, specific, verifiable material; cut platitudes.
- **Respect the slot**: timing cues must sum to the target length; flag overruns.
- **Files to `output/`**: any abstract, narrative, or deck the user wants saved goes to `output/`.