"""Memory tool for persisting architectural insights across sessions using mem0 + Azure AI Search."""

import os

from dotenv import load_dotenv
from mem0 import Memory

load_dotenv(override=True)

# mem0 configuration: Azure OpenAI for LLM & embeddings, Azure AI Search as vector store.
# Authentication uses Azure Identity (DefaultAzureCredential / az login) — no API keys required.
_config = {
    "llm": {
        "provider": "azure_openai",
        "config": {
            "model": os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT_NAME", "gpt-4o"),
            "temperature": 0.1,
            "max_tokens": 2000,
            "azure_kwargs": {
                "azure_deployment": os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT_NAME", "gpt-4o"),
                "api_version": os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21"),
                "azure_endpoint": os.environ["AZURE_OPENAI_ENDPOINT"],
            },
        },
    },
    "embedder": {
        "provider": "azure_openai",
        "config": {
            "model": os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME", "text-embedding-3-small"),
            "embedding_dims": int(os.getenv("AZURE_OPENAI_EMBEDDING_DIMENSIONS", "1536")),
            "azure_kwargs": {
                "azure_deployment": os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME", "text-embedding-3-small"),
                "api_version": os.getenv("AZURE_OPENAI_EMBEDDING_API_VERSION", "2024-10-21"),
                "azure_endpoint": os.environ["AZURE_OPENAI_ENDPOINT"],
            },
        },
    },
    "vector_store": {
        "provider": "azure_ai_search",
        "config": {
            "service_name": os.environ["AZURE_AI_SEARCH_SERVICE_NAME"],
            "collection_name": os.getenv("MEM0_COLLECTION_NAME", "researcher-memory"),
            "embedding_model_dims": int(os.getenv("AZURE_OPENAI_EMBEDDING_DIMENSIONS", "1536")),
            "hybrid_search": True,
        },
    },
}

_memory: Memory | None = None


def _get_memory() -> Memory:
    """Instantiate the mem0 client lazily so module import never fails."""
    global _memory
    if _memory is None:
        _memory = Memory.from_config(_config)
    return _memory


# Agent ID used to scope memories to this researcher agent.
_AGENT_ID = "researcher"


def save_insight(
    insight: str,
    category: str = "general",
    tags: list[str] | None = None,
) -> str:
    """Persist an architectural insight to long-term memory.

    Use this tool to save important findings, patterns, design decisions,
    or lessons learned so they are available in future sessions.

    Args:
        insight: The insight or finding to persist.
        category: Category of the insight (e.g. "pattern", "decision",
            "risk", "recommendation", "lesson-learned").
        tags: Optional list of tags for retrieval.

    Returns:
        Confirmation message with the memory ID.
    """
    metadata = {"category": category}
    if tags:
        metadata["tags"] = ",".join(tags)

    result = _get_memory().add(
        insight,
        agent_id=_AGENT_ID,
        metadata=metadata,
    )
    memory_id = result.get("id", "unknown") if isinstance(result, dict) else "stored"
    return f"Insight saved (category='{category}'). Memory ID: {memory_id}"


def recall_insights(
    query: str,
    category: str = "",
    limit: int = 10,
) -> str:
    """Recall previously saved insights from memory.

    Use this to retrieve past findings, patterns, or decisions that may
    be relevant to the current architecture task.

    Args:
        query: Semantic search query describing what you want to recall.
        category: Optional category filter (e.g. "pattern", "decision").
        limit: Maximum number of insights to return.

    Returns:
        A formatted list of matching insights from memory, or a message
        if no insights are found.
    """
    results = _get_memory().search(
        query,
        agent_id=_AGENT_ID,
        limit=limit,
    )

    # Filter by category client-side if specified
    memories = results.get("results", results) if isinstance(results, dict) else results
    if category:
        memories = [
            m for m in memories
            if m.get("metadata", {}).get("category") == category
        ]

    if not memories:
        return "No insights found in memory matching the given query."

    formatted = []
    for m in memories:
        mem_id = m.get("id", "?")
        text = m.get("memory", m.get("text", ""))
        meta = m.get("metadata", {})
        cat = meta.get("category", "general")
        tags = meta.get("tags", "")
        score = m.get("score", "")
        formatted.append(
            f"[{mem_id}] (category={cat}, score={score})\n"
            f"  {text}\n"
            f"  Tags: {tags}"
        )
    return "\n\n".join(formatted)
