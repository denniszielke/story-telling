"""Researcher deep agent.

Architecture proposals are produced by a `deepagents` agent that:

- loads its operating instructions from `memories/AGENTS.md` (always-on memory),
- loads the `architecture-research`, `visualization` and `memory-management`
  skills from `skills/` (progressive disclosure),
- requires **human-in-the-loop approval** for every search tool call,
- streams events back to its caller (the A2A executor).

The agent itself is a `langgraph` CompiledStateGraph — invocation,
streaming and HITL resumption are handled by the A2A server in
`a2a_server.py`.
"""

from __future__ import annotations

import os
from pathlib import Path

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from dotenv import load_dotenv
from langchain_core.tools import tool
from langchain_openai import AzureChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend

from searching import search_architecture_content as _search_architecture_content
from memory import save_insight as _save_insight, recall_insights as _recall_insights
from visualization import generate_visualization as _generate_visualization

load_dotenv(override=True)

_RESEARCHER_DIR = Path(__file__).resolve().parent


# -- Tools (LangChain-wrapped) -----------------------------------------------

@tool
def search_architecture_content(
    query: str,
    classification: str | None = None,
    top: int = 5,
) -> str:
    """Search the curated Azure AI Search index for grounded architecture evidence.

    Args:
        query: Natural-language search query.
        classification: Optional filter — typically "case-study" for use cases
            or "method"/"concept" for methodologies.
        top: Maximum number of hits (default 5).
    """
    return _search_architecture_content(query=query, classification=classification, top=top)


@tool
def save_insight(insight: str, category: str = "pattern", tags: list[str] | None = None) -> str:
    """Persist a durable architectural insight to long-term memory."""
    return _save_insight(insight=insight, category=category, tags=tags or [])


@tool
def recall_insights(query: str, category: str | None = None, limit: int = 10) -> str:
    """Recall previously saved insights from long-term memory via semantic search."""
    return _recall_insights(query=query, category=category, limit=limit)


@tool
def generate_visualization(
    title: str,
    scenario_description: str,
    layers: list[str],
    components: list[str],
    flows: list[str],
    callouts: list[str] | None = None,
    aspect_ratio: str = "16:9",
    output_path: str | None = None,
) -> str:
    """Generate a whiteboard-style functional architecture diagram. Returns the saved file path."""
    return _generate_visualization(
        title=title,
        scenario_description=scenario_description,
        layers=layers,
        components=components,
        flows=flows,
        callouts=callouts or [],
        aspect_ratio=aspect_ratio,
        output_path=output_path,
    )


TOOLS = [
    search_architecture_content,
    save_insight,
    recall_insights,
    generate_visualization,
]


# -- Model --------------------------------------------------------------------

def _build_model() -> AzureChatOpenAI:
    """Build the Azure OpenAI chat model with Entra ID auth."""
    credential = DefaultAzureCredential()
    token_provider = get_bearer_token_provider(
        credential, "https://cognitiveservices.azure.com/.default"
    )
    return AzureChatOpenAI(
        azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        azure_deployment=os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT_NAME", "gpt-5.4"),
        api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2025-03-01-preview"),
        azure_ad_token_provider=token_provider,
        streaming=True,
    )


# -- Agent factory ------------------------------------------------------------

SYSTEM_PROMPT = (
    "You are the Architecture Researcher. Follow the operating contract in "
    "`/memories/AGENTS.md` exactly: produce proposals with Scenario "
    "Description, Architecture Concept (with ADRs), and a Visualization. "
    "Use the loaded skills (`architecture-research`, `visualization`, "
    "`memory-management`) for every research, drawing and persistence step."
)


def build_agent(
    *,
    checkpointer: InMemorySaver | None = None,
    interrupt_on_search: bool = True,
):
    """Build the researcher deep agent.

    Args:
        checkpointer: Required to support HITL interrupts and resumption.
            One is created automatically when not provided.
        interrupt_on_search: If True (default), every `search_architecture_content`
            call is interrupted for human review before execution.
    """
    backend = FilesystemBackend(root_dir=_RESEARCHER_DIR, virtual_mode=True)
    interrupt_on = {"search_architecture_content": True} if interrupt_on_search else None

    return create_deep_agent(
        model=_build_model(),
        tools=TOOLS,
        system_prompt=SYSTEM_PROMPT,
        skills=["/skills/"],
        memory=["/memories/AGENTS.md"],
        backend=backend,
        checkpointer=checkpointer or InMemorySaver(),
        interrupt_on=interrupt_on,
        name="researcher",
    )


if __name__ == "__main__":
    import sys
    import uuid

    agent = build_agent(interrupt_on_search=False)  # auto-run for CLI
    user_query = " ".join(sys.argv[1:]) or (
        "Create an architecture proposal for a multi-agent system that helps "
        "field service engineers diagnose and resolve equipment issues using "
        "AI-powered knowledge retrieval and real-time sensor data."
    )
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    result = agent.invoke(
        {"messages": [{"role": "user", "content": user_query}]}, config=config
    )
    print(result["messages"][-1].content)
