"""MCP Server for architecture research - searching case studies and recommending methodologies."""

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Optional

# Ensure the project src directory is in the path
project_root = Path(__file__).parent.parent.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from azure.identity import DefaultAzureCredential
from azure.search.documents import SearchClient
from azure.search.documents.models import VectorizedQuery
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from openai import AzureOpenAI

load_dotenv(override=True)

# Initialize Azure credentials and clients
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
    search_mode: str = "architecture",
) -> dict:
    """Search the AI Search index for architecture-relevant content.

    Args:
        query: Natural language query describing what you are looking for
        classification: Optional filter on document classification
            (e.g. "case-study", "concept", "method").
        top: Maximum number of results to return.
        search_mode: Whether to search the scenario field or architecture content.

    Returns:
        Dictionary with structured search results.
    """
    vector_field = "scenario_vector" if search_mode == "scenario" else "content_vector"
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

    documents = []
    for doc in results:
        documents.append({
            "id": doc.get("id"),
            "description": doc.get("description"),
            "classification": doc.get("classification"),
            "objective": doc.get("objective"),
            "scenario": doc.get("scenario"),
            "context": doc.get("context"),
            "content_preview": doc.get("content", "")[:500],
            "source": doc.get("source"),
            "reference": doc.get("reference"),
            "tags": doc.get("tags", []),
            "rating": doc.get("rating"),
        })

    return {
        "query": query,
        "classification_filter": classification,
        "search_mode": search_mode,
        "vector_field": vector_field,
        "results_count": len(documents),
        "documents": documents,
    }


# Remote MCP server settings (localhost by default)
MCP_HOST = os.getenv("RESEARCH_MCP_HOST", "127.0.0.1")
MCP_PORT = int(os.getenv("RESEARCH_MCP_PORT", "8000"))
MCP_PATH = os.getenv("RESEARCH_MCP_PATH", "/mcp")

# Initialize MCP server (streamable HTTP transport)
mcp = FastMCP(
    name="research-mcp",
    host=MCP_HOST,
    port=MCP_PORT,
    streamable_http_path=MCP_PATH,
)

# Backward compatibility for previous imports
server = mcp


@mcp.tool(
    name="search_comparable_case_studies",
    description=(
        "Search for comparable case studies based on scenario description. "
        "Use this to find similar customer scenarios that have already been "
        "implemented and documented."
    ),
)
def search_comparable_case_studies(scenario_description: str, top_results: int = 5) -> dict:
    """Search for comparable case studies."""
    try:
        return search_architecture_content(
            query=scenario_description,
            classification="case-study",
            top=top_results,
            search_mode="scenario",
        )
    except Exception as e:
        return {"error": f"Error searching case studies: {str(e)}"}


@mcp.tool(
    name="recommend_methodology",
    description=(
        "Recommend architectural methodologies and patterns for a given problem "
        "statement. Returns relevant methodologies, patterns, and best practices "
        "from the knowledge base."
    ),
)
def recommend_methodology(problem_statement: str, top_results: int = 5) -> dict:
    """Recommend methodology for a problem statement."""
    try:
        return search_architecture_content(
            query=problem_statement,
            classification="method",
            top=top_results,
            search_mode="architecture",
        )
    except Exception as e:
        return {"error": f"Error recommending methodology: {str(e)}"}


@mcp.tool(
    name="search_scenarios",
    description=(
        "Search the scenario field independently from the solution content. "
        "Use this to find similar industries, use cases, constraints, or problem statements."
    ),
)
def search_scenarios(
    scenario_query: str,
    classification: Optional[str] = None,
    top_results: int = 5,
) -> dict:
    """Search indexed scenario summaries."""
    try:
        return search_architecture_content(
            query=scenario_query,
            classification=classification,
            top=top_results,
            search_mode="scenario",
        )
    except Exception as e:
        return {"error": f"Error searching scenarios: {str(e)}"}


@mcp.tool(
    name="search_architectures",
    description=(
        "Search the architecture and solution content independently from the scenario. "
        "Use this to find implementation approaches, platform choices, and design patterns."
    ),
)
def search_architectures(
    architecture_query: str,
    classification: Optional[str] = None,
    top_results: int = 5,
) -> dict:
    """Search indexed architecture and solution content."""
    try:
        return search_architecture_content(
            query=architecture_query,
            classification=classification,
            top=top_results,
            search_mode="architecture",
        )
    except Exception as e:
        return {"error": f"Error searching architectures: {str(e)}"}


async def main():
    """Run the MCP server over Streamable HTTP (remote transport)."""
    # FastMCP provides an async entrypoint for streamable HTTP transport.
    await mcp.run_streamable_http_async()


def run():
    """Entry point for installed script."""
    try:
        print(
            f"Starting remote MCP server at http://{MCP_HOST}:{MCP_PORT}{MCP_PATH}",
            file=sys.stderr,
        )
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Server shutting down...", file=sys.stderr)
        sys.exit(0)
    except Exception as e:
        print(f"Fatal error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    run()
