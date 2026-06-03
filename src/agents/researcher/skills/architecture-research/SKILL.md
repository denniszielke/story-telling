---
name: architecture-research
description: Search the curated Azure AI Search index for grounded architecture evidence — real customer use cases (objective="use case") and methodologies (objective="method"). Invoke before writing any section of an architecture proposal so claims, components and decisions are evidence-backed.
allowed-tools:
  - search_architecture_content
---

# Architecture Research

Use this skill whenever you need to ground an architecture proposal in real
evidence. The index contains two complementary kinds of documents:

- **Use cases** — customer stories (e.g. BMW, Commerzbank, KUKA, Bayer). Pass
  `classification="case-study"` or simply rely on the natural-language query.
- **Methods** — methodologies, patterns and templates (Squad architecture,
  Compound engineering, ADRs, WAF). Pass `classification="method"` or
  `"concept"`.

## When to call

1. **Before drafting the Scenario Description** — search for analogous
   customer scenarios.
2. **Before drafting the Architecture Concept** — search for proven
   component patterns and integration approaches.
3. **Before recording Architecture Decisions** — search for relevant
   methodology (ADR templates, WAF pillars, design heuristics).

## How to call

```
search_architecture_content(
    query="multi-agent field service diagnosis with sensor telemetry",
    classification="case-study",   # or "method" / omit for hybrid
    top=5,
)
```

The tool returns a markdown block with id, objective, description, source,
reference, tags and the extracted content for each hit. Always cite the
`source` URL when you reuse a finding in the final proposal.

## Human-in-the-loop

Every call to `search_architecture_content` is interrupted for human review
before execution. Compose a precise query and explain why it advances the
proposal so the reviewer can approve, edit, or reject quickly.
