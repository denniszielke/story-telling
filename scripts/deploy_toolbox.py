"""Create or update the Foundry Toolbox that hosted agents consume at runtime."""

import os

from azure.ai.projects.models import (
    AISearchIndexResource,
    AzureAISearchQueryType,
    AzureAISearchTool,
    AzureAISearchToolResource,
    WebSearchTool,
)

from deploy_helpers import get_client, get_env

TOOLBOX_NAME = "researcher-tools"


def _build_web_search_tool(client) -> WebSearchTool | dict | None:
    """Bing Custom Web Search tool, or None when not configured."""
    bing_conn_name = os.environ.get("BING_CUSTOM_GROUNDING_CONNECTION_NAME", "")
    if not bing_conn_name:
        print("  BING_CUSTOM_GROUNDING_CONNECTION_NAME not set — skipping web search tool.")
        return None

    instance_name = os.environ.get("BING_CUSTOM_GROUNDING_CONFIG_INSTANCE_NAME", "default")
    bing_conn_id = client.connections.get(bing_conn_name).id

    try:
        return WebSearchTool(
            name="web_search",
            custom_search_configuration={
                "project_connection_id": bing_conn_id,
                "instance_name": instance_name,
            },
        )
    except TypeError:
        return {  # type: ignore[return-value]
            "type": "web_search",
            "name": "web_search",
            "web_search": {
                "custom_search_configuration": {
                    "project_connection_id": bing_conn_id,
                    "instance_name": instance_name,
                },
            },
        }


def _build_ai_search_tool(client) -> AzureAISearchTool | None:
    """Azure AI Search tool over the curated index, or None when not configured."""
    search_conn_name = os.environ.get("AZURE_AI_SEARCH_CONNECTION_NAME", "")
    index_name = os.environ.get("AZURE_AI_SEARCH_INDEX_NAME", "")
    if not search_conn_name or not index_name:
        print(
            "  AZURE_AI_SEARCH_CONNECTION_NAME / AZURE_AI_SEARCH_INDEX_NAME not set — "
            "skipping AI Search tool."
        )
        return None

    search_conn_id = client.connections.get(search_conn_name).id

    # The curated index has vector fields but no server-side vectorizer or
    # semantic configuration, so the managed tool uses keyword (SIMPLE) queries.
    return AzureAISearchTool(
        name="azure_ai_search",
        azure_ai_search=AzureAISearchToolResource(
            indexes=[
                AISearchIndexResource(
                    project_connection_id=search_conn_id,
                    index_name=index_name,
                    query_type=AzureAISearchQueryType.SIMPLE,
                    top_k=int(os.environ.get("AZURE_AI_SEARCH_TOP_K", "5")),
                )
            ]
        ),
    )


def deploy() -> None:
    client = get_client()

    tools: list = []
    web_search = _build_web_search_tool(client)
    if web_search is not None:
        tools.append(web_search)
    ai_search = _build_ai_search_tool(client)
    if ai_search is not None:
        tools.append(ai_search)

    if not tools:
        print("No toolbox tools configured — skipping toolbox deploy.")
        return

    project_endpoint = get_env("AZURE_AI_PROJECT_ENDPOINT")

    version = client.beta.toolboxes.create_version(
        name=TOOLBOX_NAME,
        description=(
            "Researcher shared toolbox — Bing Custom Web Search and Azure AI Search "
            "over the curated architecture index for grounded research"
        ),
        tools=tools,
    )

    consumer_endpoint = f"{project_endpoint}/toolboxes/{TOOLBOX_NAME}/mcp?api-version=v1"
    tool_types = ", ".join(
        (t.get("type") if isinstance(t, dict) else getattr(t, "type", type(t).__name__))
        for t in tools
    )
    print(f"Toolbox '{TOOLBOX_NAME}' version '{version.version}' created with tools: {tool_types}.")
    print(f"  Consumer endpoint: {consumer_endpoint}")


if __name__ == "__main__":
    deploy()
