"""Researcher agent — retrieves architecture content from AI Search and persists insights via mem0."""

from deepagents import create_deep_agent

from searching import search_architecture_content
from memory import save_insight, recall_insights

SYSTEM_PROMPT = """\
You are an expert architecture researcher. Your job is to find relevant content
for creating architecture concepts — including patterns, case studies, methods,
and strategic approaches.

## Tools

### `search_architecture_content`
Use this to query the Azure AI Search index for relevant architecture knowledge.
You can filter by classification (e.g. "case-study", "concept", "method") and
adjust the number of results.

### `save_insight`
When you discover an important pattern, decision, risk, or recommendation,
persist it to memory so it is available in future sessions. Always categorise
insights appropriately (pattern, decision, risk, recommendation, lesson-learned).

### `recall_insights`
Use semantic search to retrieve previously saved insights from long-term memory.
Pass a descriptive query — the memory layer uses vector similarity to find
relevant past findings even if wording differs.

## Workflow
1. Recall any relevant insights from memory first.
2. Search the index for matching architecture content.
3. Synthesise findings into a clear, structured response.
4. Save any new key insights to memory for future use.

Keep responses concise and actionable. Cite sources where available.
"""

agent = create_deep_agent(
    model="azure_openai:gpt-4o",
    tools=[search_architecture_content, save_insight, recall_insights],
    system_prompt=SYSTEM_PROMPT,
)

if __name__ == "__main__":
    import sys

    query = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "What architecture patterns are relevant for multi-agent systems?"
    result = agent.invoke({"messages": [{"role": "user", "content": query}]})
    print(result["messages"][-1].content)
