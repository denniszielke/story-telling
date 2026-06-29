---
name: use-case-processing
description: |
  Processing skill for assets classified as "use case". Fetches the customer story, runs the
  case-study extraction prompt to split the narrative into an enterprise `scenario` and a
  solution-focused `content` body, enriches image artifacts, generates tags, and returns an
  index-ready document. Invoked by the ingestion agent when asset-identification returns
  objective == "use case".
objective: use case
processor: case-study
---

# Use Case Processing

Handles customer stories and case studies. The heavy lifting is performed by the shared
`ContentExtractor` using the `case-study-extraction.md` system prompt, so this skill is a thin,
auditable contract over that extractor.

## Inputs

A base document produced by **asset-identification**:

```json
{ "objective": "use case", "classification": "...", "description": "...", "reference": "<url>", "source": "internet" }
```

## Procedure

1. **Fetch** readable text from `reference` (HTML stripped of nav/script/style).
2. **Extract** structured analysis with the case-study prompt (objective = `use case`):
   - Industry and business domain, operating context, the core problem and why it mattered →
     the `scenario` field.
   - Solution approach, architecture concept, implementation details, outcomes, and
     transferable learnings → the `content` field.
3. **Split** the extracted markdown: the `## Scenario` section becomes `scenario`; the remainder
   becomes `content`.
4. **Artifacts**: describe any referenced images via the vision model and attach them as
   `artifacts` (reference/type/description).
5. **Tags**: generate ≤10 lowercase descriptive tags (technologies, the named organisation,
   industry, architecture patterns), preserving any provided tags.

## Output

An enriched document with non-empty `scenario` and `content`, ready for embedding and upsert.
A `scenario` is **required** for this objective; if extraction yields none, fall back to the
description plus context/classification before indexing.

## Guardrails

- No personal names. Precise product names. Analytical phrasing, not marketing copy.
- Do not invent outcomes that are not stated or clearly implied in the source.
