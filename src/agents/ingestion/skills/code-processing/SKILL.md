---
name: code-processing
description: |
  Processing skill for assets classified as "code". Resolves the repository from its URL, pulls
  GitHub metadata plus the default README (never source files), runs the repository-extraction
  prompt to produce a solution-focused `content` body, merges repository-derived tags, and returns
  an index-ready document. Invoked by the ingestion agent when asset-identification returns
  objective == "code".
objective: code
processor: repository
---

# Code Processing

Handles software repositories and code artifacts. The shared `RepositoryContentExtractor` performs
the work using GitHub REST metadata and the default README only, driven by the
`repository-extraction.md` system prompt. This skill is the contract over that extractor.

## Inputs

A base document produced by **asset-identification**:

```json
{ "objective": "code", "classification": "...", "description": "...", "reference": "<github url>", "source": "internet" }
```

## Procedure

1. **Resolve** `owner/repo` from the `reference` URL (GitHub only).
2. **Snapshot** repository metadata (language, topics, stars/forks/issues, license, timestamps,
   homepage) and fetch the **default README** — do not read or infer from source files.
3. **Extract** with the repository prompt → a one-line purpose summary plus a `## Scenario`
   section (domain, target users, problem, constraints) and a solution-focused `content` body
   (architecture approach, implementation model, capabilities, operational signals).
4. **Tags**: merge repository language/topics with any provided tags (≤10, lowercase).

## Output

An enriched document with `content` populated and, when the prompt emits one, a `scenario`.
For the `code` objective a `scenario` is **optional** — the document indexes even without one.

## Guardrails

- No personal names. Use product/technology names exactly as stated.
- Metadata + README only; never claim behaviour that is not evidenced by those sources.
