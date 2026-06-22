"""Azure AI Search tool for the researcher agent."""

import os
from typing import Optional

from azure.identity import DefaultAzureCredential
from azure.search.documents import SearchClient
from azure.search.documents.models import VectorizedQuery
from dotenv import load_dotenv
from openai import AzureOpenAI

load_dotenv(override=True)

_credential = DefaultAzureCredential()

_search_client = SearchClient(
    endpoint=os.environ["AZURE_AI_SEARCH_ENDPOINT"],
    index_name=os.environ["AZURE_AI_SEARCH_INDEX_NAME"],
    credential=_credential,
)

def _get_embedding(text: str) -> list[float]:
    """Generate an embedding vector for a query string."""
    from azure.identity import get_bearer_token_provider

    token_provider = get_bearer_token_provider(
        _credential, "https://cognitiveservices.azure.com/.default"
    )
    client = AzureOpenAI(
        azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        azure_deployment=os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME", "text-embedding-3-small"),
        api_version=os.getenv("AZURE_OPENAI_EMBEDDING_API_VERSION", "2024-10-21"),
        azure_ad_token_provider=token_provider,
    )
    dimensions = int(os.getenv("AZURE_OPENAI_EMBEDDING_DIMENSIONS", "1536"))
    response = client.embeddings.create(
        input=text,
        model=os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME", "text-embedding-3-small"),
        dimensions=dimensions,
    )
    return response.data[0].embedding


def search_architecture_documents(
    query: str,
    classification: Optional[str] = None,
    objective: Optional[str] = None,
    top: int = 5,
    filter_expr: Optional[str] = None,
) -> list[dict]:
    """Search the AI Search index and return matching documents as dicts.

    Args:
        query: Natural language query.
        classification: Optional filter on `classification` field.
        objective: Optional filter on `objective` field.
        top: Maximum number of results.
        filter_expr: Optional raw OData filter expression.
            When provided with other filters, all clauses are AND-combined.
    """
    normalized_objective = (objective or "").strip().lower()
    vector_field = "scenario_vector" if normalized_objective == "use case" else "content_vector"
    vector = _get_embedding(query)
    vector_query = VectorizedQuery(
        vector=vector,
        k_nearest_neighbors=top,
        fields=vector_field,
    )

    clauses = []
    if classification:
        escaped = classification.replace("'", "''")
        clauses.append(f"classification eq '{escaped}'")
    if objective:
        escaped = objective.replace("'", "''")
        clauses.append(f"objective eq '{escaped}'")
    if filter_expr:
        clauses.append(f"({filter_expr})")
    effective_filter = " and ".join(clauses) if clauses else None

    results = _search_client.search(
        search_text=query,
        vector_queries=[vector_query],
        filter=effective_filter,
        top=top,
        select=[
            "id",
            "objective",
            "description",
            "classification",
            "scenario",
            "context",
            "content",
            "source",
            "reference",
            "tags",
            "rating",
        ],
    )

    return [dict(doc) for doc in results]


def search_architecture_content(
    query: str,
    classification: Optional[str] = None,
    top: int = 5,
) -> str:
    """Search the AI Search index for architecture-relevant content.

    Args:
        query: Natural language query describing what you are looking for
            (e.g. "multi-agent patterns for enterprise" or "event-driven architecture").
        classification: Optional filter on document classification
            (e.g. "case-study", "concept", "method").
        top: Maximum number of results to return.

    Returns:
        A formatted string with the top matching documents including their
        description, classification, context, content, source and rating.
    """
    results = search_architecture_documents(
        query=query,
        classification=classification,
        top=top,
    )

    formatted = []
    for doc in results:
        entry = (
            f"---\n"
            f"**{doc['description']}**\n"
            f"- Classification: {doc.get('classification', 'n/a')}\n"
            f"- Objective: {doc.get('objective', 'n/a')}\n"
            f"- Scenario: {doc.get('scenario', 'n/a')[:400]}\n"
            f"- Context: {doc.get('context', 'n/a')}\n"
            f"- Source: {doc.get('source', 'n/a')}\n"
            f"- Reference: {doc.get('reference', 'n/a')}\n"
            f"- Tags: {', '.join(doc.get('tags', []))}\n"
            f"- Rating: {doc.get('rating', 'n/a')}\n"
            f"- Content: {doc.get('content', '')[:500]}\n"
        )
        formatted.append(entry)

    if not formatted:
        return "No results found for the given query."

    return "\n".join(formatted)
