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
    vector_field = "scenario_vector" if classification == "case-study" else "content_vector"
    vector = _get_embedding(query)
    vector_query = VectorizedQuery(
        vector=vector,
        k_nearest_neighbors=top,
        fields=vector_field,
    )

    filter_expr = None
    if classification:
        filter_expr = f"classification eq '{classification}'"

    results = _search_client.search(
        search_text=query,
        vector_queries=[vector_query],
        filter=filter_expr,
        top=top,
        select=["id", "objective", "description", "classification", "scenario", "context", "content", "source", "reference", "tags", "rating"],
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
