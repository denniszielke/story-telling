---
name: memory-management
description: Persist durable architectural insights (patterns, decisions, risks, recommendations, lessons-learned) to long-term memory and recall them on future runs. Use to build a compounding knowledge base across proposals.
allowed-tools:
  - save_insight
  - recall_insights
---

# Long-term Memory

This skill complements the always-on `AGENTS.md` file. It targets
**semantically searchable, structured insights** that survive across
sessions, stored in the Azure AI Search–backed mem0 store.

## When to recall (`recall_insights`)

- At the **start of every proposal**, query for prior insights matching the
  scenario keywords. Cite them in your reasoning.
- When a tricky decision arises (security, scale, cost), recall by
  `category="decision"` or `category="risk"`.

```
recall_insights(query="multi-agent orchestration patterns", category="pattern", limit=10)
```

## When to save (`save_insight`)

After delivering a proposal, persist what is worth re-using:

| category          | what to record                                              |
| ----------------- | ----------------------------------------------------------- |
| `pattern`         | a reusable structural or integration pattern                |
| `decision`        | an ADR-style choice with rationale                          |
| `risk`            | a recurring risk and its mitigation                         |
| `recommendation`  | a "default" recommendation for similar scenarios            |
| `lesson-learned`  | something that surprised you or contradicted prior belief   |

```
save_insight(
    insight="Use a planner sub-agent + worker pool for >3 specialist agents",
    category="pattern",
    tags=["multi-agent", "orchestration"],
)
```

Keep each insight to a single, self-contained sentence — it must be useful
out of context six months from now.
