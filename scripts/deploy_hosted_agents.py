"""Build container images and deploy hosted agents to Azure AI Foundry."""

import sys
from pathlib import Path

from azure.ai.projects.models import (
    HostedAgentDefinition,
    ProtocolVersionRecord,
    AgentProtocol,
    AgentEndpointConfig,
    AgentEndpointProtocol,
    AgentCard,
    AgentCardSkill,
    ContainerConfiguration,
    MCPTool,
)

# Allow running from tools/ directory
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from agents import discover_hosted_agents
from deploy_helpers import (
    account_scope_from_project_id,
    assign_azure_ai_user_role,
    assign_cognitive_services_openai_user_role,
    build_image,
    get_client,
    get_env,
)
from deploy_toolbox import TOOLBOX_NAME


# Agent card definitions keyed by agent name
AGENT_CARDS: dict[str, AgentCard] = {
    "researcher": AgentCard(
        description="Researcher deep agent — produces architecture proposals grounded in curated research",
        version="1.0",
        skills=[
            AgentCardSkill(
                id="architecture-research",
                name="Architecture Research",
                description="Search curated architecture content and customer evidence to ground proposals",
            ),
            AgentCardSkill(
                id="visualization",
                name="Visualization",
                description="Generate architecture diagrams and visualizations for proposals",
            ),
            AgentCardSkill(
                id="memory-management",
                name="Memory Management",
                description="Persist and recall research insights across sessions",
            ),
        ],
    ),
}


def deploy() -> None:
    client = get_client()

    project_endpoint = get_env("AZURE_AI_PROJECT_ENDPOINT")
    model_deployment_name = get_env("AZURE_AI_MODEL_DEPLOYMENT_NAME", default="gpt-4.1-mini")
    aoai_endpoint = get_env("AZURE_OPENAI_ENDPOINT")
    openai_api_version = get_env("OPENAI_API_VERSION", default="2024-05-01-preview")
    registry = get_env("AZURE_CONTAINER_REGISTRY_ENDPOINT")
    project_arm_id = get_env("AZURE_AI_PROJECT_ID", required=False, default="") or ""

    protocols = [ProtocolVersionRecord(protocol=AgentProtocol.RESPONSES, version="1.0.0")]

    toolbox_endpoint = f"{project_endpoint}/toolboxes/{TOOLBOX_NAME}/mcp?api-version=v1"

    # Azure AI Search configuration — required by the researcher's direct
    # search/memory code paths inside the container.
    search_endpoint = get_env("AZURE_AI_SEARCH_ENDPOINT", required=False, default="") or ""
    search_index_name = get_env("AZURE_AI_SEARCH_INDEX_NAME", required=False, default="") or ""
    search_service_name = get_env("AZURE_AI_SEARCH_SERVICE_NAME", required=False, default="") or ""
    embedding_deployment = get_env(
        "AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME", required=False, default="text-embedding-3-small"
    )

    hosted_env = {
        "MODEL_DEPLOYMENT_NAME": model_deployment_name,
        "AZURE_AI_PROJECT_ENDPOINT": project_endpoint,
        "AZURE_AI_MODEL_DEPLOYMENT_NAME": model_deployment_name,
        "AZURE_OPENAI_CHAT_DEPLOYMENT_NAME": model_deployment_name,
        "AZURE_OPENAI_ENDPOINT": aoai_endpoint,
        "OPENAI_API_VERSION": openai_api_version,
        "TOOLBOX_NAME": TOOLBOX_NAME,
        "TOOLBOX_MCP_ENDPOINT": toolbox_endpoint,
        "AZURE_AI_SEARCH_ENDPOINT": search_endpoint,
        "AZURE_AI_SEARCH_INDEX_NAME": search_index_name,
        "AZURE_AI_SEARCH_SERVICE_NAME": search_service_name,
        "AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME": embedding_deployment,
    }

    # Tool that links the shared toolbox (Bing web search + Azure AI Search)
    # to the hosted agent via the toolbox's MCP endpoint.
    toolbox_tool = MCPTool(
        server_label=TOOLBOX_NAME.replace("-", "_"),
        server_url=toolbox_endpoint,
        require_approval="never",
    )

    # Source agents live under src/agents/
    agents_src = Path(__file__).parent.parent / "src" / "agents"

    for config in discover_hosted_agents():
        if not (config.path / "Dockerfile").exists():
            print(f"Skipping '{config.name}': no Dockerfile found")
            continue

        image_tag = build_image(registry, config.name, config.path)
        env_vars = {**hosted_env, **config.env_vars}

        agent = client.agents.create_version(
            agent_name=config.name,
            description=config.description,
            definition=HostedAgentDefinition(
                protocol_versions=protocols,
                cpu=config.cpu,
                memory=config.memory,
                container_configuration=ContainerConfiguration(image=image_tag),
                environment_variables=env_vars,
                tools=[toolbox_tool],
            ),
            metadata={"enableVnextExperience": "true", "voiceLiveCompatible": "true"},
            headers={"Foundry-Features": "HostedAgents=V1Preview"},
        )
        print(f"Hosted agent '{config.name}' created: {agent.id}")
        print(f"  Linked toolbox '{TOOLBOX_NAME}' via MCP: {toolbox_endpoint}")

        endpoint_config = AgentEndpointConfig(
            protocols=[
                AgentEndpointProtocol.RESPONSES,
                AgentEndpointProtocol.A2A,
                AgentEndpointProtocol.INVOCATIONS,
            ],
        )
        agent_card = AGENT_CARDS.get(config.name)
        if agent_card:
            client.beta.agents.patch_agent_details(
                agent_name=config.name,
                agent_endpoint=endpoint_config,
                agent_card=agent_card,
            )
            a2a_base = f"{project_endpoint.rstrip('/')}/agents/{config.name}/endpoint/protocols/a2a"
            print(f"  A2A enabled — v1.0 card: {a2a_base}/agentCard/v1.0")
            print(f"            (v0.3 card: {a2a_base}/agentCard/v0.3)")
        else:
            print(f"  WARNING: no agent card defined for '{config.name}', skipping A2A setup.")

        principal_id = _extract_principal_id(agent)
        if principal_id and project_arm_id:
            assign_azure_ai_user_role(principal_id, project_arm_id)
            # The agent calls the OpenAI data plane directly, so it also needs
            # the OpenAI User role on the parent AI Services account.
            assign_cognitive_services_openai_user_role(
                principal_id, account_scope_from_project_id(project_arm_id)
            )
        elif not principal_id:
            print(f"  WARNING: could not find agent identity principal for '{config.name}'.")
        elif not project_arm_id:
            print("  WARNING: AZURE_AI_PROJECT_ID not set — skipping RBAC assignment.")


def _extract_principal_id(agent_version) -> str | None:
    """Best-effort extraction of the agent's Entra identity principal ID."""
    for attr in ("blueprint", "instance_identity", "identity", "agent_identity", "system_assigned_identity"):
        identity = getattr(agent_version, attr, None)
        if identity is None:
            continue
        for sub in ("principal_id", "principalId", "object_id", "objectId"):
            value = getattr(identity, sub, None)
            if not value and isinstance(identity, dict):
                value = identity.get(sub)
            if value:
                return value
    as_dict = getattr(agent_version, "as_dict", None)
    if callable(as_dict):
        data = as_dict()
        for key in ("blueprint", "instance_identity", "identity", "agentIdentity"):
            identity = data.get(key)
            if identity:
                value = identity.get("principal_id") or identity.get("principalId")
                if value:
                    return value
    return None


if __name__ == "__main__":
    deploy()
