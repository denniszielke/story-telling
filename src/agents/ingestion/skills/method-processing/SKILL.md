---
name: method-processing
description: |
  Processing skill for assets classified as "method". Fetches the guide/article/documentation,
  runs the methodology pattern-analysis prompt to separate the enterprise `scenario` (problem
  space, adoption trigger) from the `content` (methodology, approach, trade-offs, outcomes),
  generates tags, and returns an index-ready document. Invoked by the ingestion agent when
  asset-identification returns objective == "method".
objective: method
processor: concept
---

# Method Processing

Handles methodologies, frameworks, architectural patterns, engineering practices, and concept
articles. The shared `ContentExtractor` runs the `methodology_pattern_analysis.md` system prompt;
this skill is a thin contract over that extractor.

## Inputs

A base document produced by **asset-identification**:

```json
{ "objective": "method", "classification": "...", "description": "...", "reference": "<url>", "source": "internet" }
```

## Procedure

1. **Fetch** readable text from `reference`.
2. **Extract** with the methodology prompt (objective = `method`):
   - The enterprise situation, problem space, and adoption trigger → `scenario`.
   - The methodology, solution approach, preconditions, trade-offs, alternatives, and measurable
     impact → `content`.
3. **Split** the extracted markdown into `scenario` and `content`.
4. **Tags**: generate ≤10 lowercase descriptive tags (technologies, patterns, key concepts),
   preserving any provided tags.

## Output

An enriched document with non-empty `scenario` and `content`. A `scenario` is **required** for
this objective; if extraction yields none, fall back to the description plus context/classification
before indexing.

## Guardrails

- No personal names. You MAY include product, technology, and company names when stated.
- Focus on insight (problem, approach, success factors, trade-offs) — skip generic statements.
