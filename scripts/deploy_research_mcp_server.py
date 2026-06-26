"""Build and deploy the Research MCP server to Azure Container Apps.

Mirrors the pricing-mcp-server deploy flow from the agentic-supply-chain repo:
remote-build the image in Azure Container Registry (ACR Tasks — no local Docker
daemon required) and deploy it as a Container App that serves the architecture
research MCP endpoint over streamable HTTP.

Usage::

    # build the image in ACR, then deploy (first deploy or after code changes)
    python scripts/deploy_research_mcp_server.py --build

    # deploy only — image already in ACR, uses :latest (or the TAG env var)
    python scripts/deploy_research_mcp_server.py

Environment variables (populated automatically from ``.env`` after ``azd up``):
  AZURE_CONTAINER_REGISTRY_ENDPOINT   ACR login server, e.g. myacr.azurecr.io (required)
  AZURE_RESOURCE_GROUP                target resource group (required)
  AZURE_CONTAINER_APPS_ENVIRONMENT    Container Apps environment name (required)
  AZURE_AI_SEARCH_ENDPOINT            Azure AI Search endpoint (required at runtime)
  AZURE_AI_SEARCH_INDEX_NAME          search index name (required at runtime)
  AZURE_OPENAI_ENDPOINT               Azure OpenAI endpoint (required at runtime)
  AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME   embedding deployment (optional)
  AZURE_OPENAI_EMBEDDING_DIMENSIONS        embedding dimensions (optional)
  AZURE_OPENAI_EMBEDDING_API_VERSION       embedding API version (optional)
  RESEARCH_MCP_APP_NAME               Container App name (default: research-mcp-server)
  RESEARCH_MCP_PORT                   container target port (default: 8000)
  RESEARCH_MCP_EXTERNAL               "true"/"false" external ingress (default: true)
  TAG                                 image tag to deploy (default: latest)
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Allow running the script directly (python scripts/deploy_research_mcp_server.py)
sys.path.insert(0, str(Path(__file__).parent))

from deploy_helpers import (  # noqa: E402
    _assign_role,
    assign_cognitive_services_openai_user_role,
    get_env,
)

# Search Index Data Reader role — lets the Container App's managed identity read
# documents from the Azure AI Search index via DefaultAzureCredential.
_SEARCH_INDEX_DATA_READER_ROLE_ID = "1407120a-92aa-4202-b7e9-c0e197c71c8f"

_REPO_ROOT = Path(__file__).resolve().parents[1]
_IMAGE_NAME = "research-mcp-server"
_DOCKERFILE = "src/mcp_server/research_mcp_server/Dockerfile"

APP_NAME = os.getenv("RESEARCH_MCP_APP_NAME", _IMAGE_NAME)
PORT = int(os.getenv("RESEARCH_MCP_PORT", "8000"))


def _registry_name(login_server: str) -> str:
    """Strip the .azurecr.io suffix to get the bare ACR resource name."""
    return login_server.split(".")[0]


def build() -> str:
    """Remote-build the image in ACR with a timestamped tag **and** :latest.

    Returns the concrete timestamp tag that was built so it can be passed
    straight to the deploy step.
    """
    registry = get_env("AZURE_CONTAINER_REGISTRY_ENDPOINT")
    registry_name = _registry_name(registry)
    build_tag = datetime.now().strftime("%Y%m%d%H%M%S")
    dockerfile = Path(_DOCKERFILE)

    print(f"🏗️  Remote-building {registry}/{_IMAGE_NAME}:{build_tag} (also :latest)")
    print(f"   registry: {registry_name}")
    print(f"   context:  {_REPO_ROOT}")
    print("   (this runs in the cloud via ACR Tasks — no local Docker needed)\n")

    subprocess.run(
        [
            "az", "acr", "build",
            "--registry", registry_name,
            "--image", f"{_IMAGE_NAME}:{build_tag}",
            "--image", f"{_IMAGE_NAME}:latest",
            "--platform", "linux/amd64",
            "--file", str(dockerfile),
            str(_REPO_ROOT),
        ],
        check=True,
    )
    print(f"\n✅ Built and pushed: {registry}/{_IMAGE_NAME}:{build_tag}")
    return build_tag


def _app_exists(resource_group: str, name: str) -> bool:
    result = subprocess.run(
        ["az", "containerapp", "show", "-g", resource_group, "-n", name, "-o", "none"],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def _container_env_vars() -> list[str]:
    """Runtime env vars the server needs, as ``KEY=VALUE`` strings for the CLI."""
    candidates = {
        "RESEARCH_MCP_HOST": "0.0.0.0",
        "RESEARCH_MCP_PORT": str(PORT),
        "RESEARCH_MCP_PATH": os.getenv("RESEARCH_MCP_PATH", "/mcp"),
        "AZURE_AI_SEARCH_ENDPOINT": get_env("AZURE_AI_SEARCH_ENDPOINT"),
        "AZURE_AI_SEARCH_INDEX_NAME": get_env("AZURE_AI_SEARCH_INDEX_NAME"),
        "AZURE_OPENAI_ENDPOINT": get_env("AZURE_OPENAI_ENDPOINT"),
        "AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME": os.getenv(
            "AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME", ""
        ),
        "AZURE_OPENAI_EMBEDDING_DIMENSIONS": os.getenv("AZURE_OPENAI_EMBEDDING_DIMENSIONS", ""),
        "AZURE_OPENAI_EMBEDDING_API_VERSION": os.getenv("AZURE_OPENAI_EMBEDDING_API_VERSION", ""),
    }
    return [f"{k}={v}" for k, v in candidates.items() if v]


def _acr_id(registry_name: str) -> str:
    result = subprocess.run(
        ["az", "acr", "show", "--name", registry_name, "--query", "id", "-o", "tsv"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def deploy(tag: str | None = None) -> None:
    resource_group = get_env("AZURE_RESOURCE_GROUP")
    environment = get_env("AZURE_CONTAINER_APPS_ENVIRONMENT")
    registry = get_env("AZURE_CONTAINER_REGISTRY_ENDPOINT")
    registry_name = _registry_name(registry)
    tag = tag or os.getenv("TAG", "latest")
    external = os.getenv("RESEARCH_MCP_EXTERNAL", "true").strip().lower() == "true"

    image_ref = f"{registry}/{_IMAGE_NAME}:{tag}"
    env_vars = _container_env_vars()

    if _app_exists(resource_group, APP_NAME):
        print(f"==> Updating Container App '{APP_NAME}' with image {image_ref}")
        subprocess.run(
            [
                "az", "containerapp", "update",
                "-g", resource_group, "-n", APP_NAME,
                "--image", image_ref,
                "--set-env-vars", *env_vars,
            ],
            check=True,
        )
        subprocess.run(
            [
                "az", "containerapp", "ingress", "update",
                "-g", resource_group, "-n", APP_NAME,
                "--type", "external" if external else "internal",
                "--target-port", str(PORT),
            ],
            check=True,
        )
    else:
        print(f"==> Creating Container App '{APP_NAME}' with image {image_ref}")
        subprocess.run(
            [
                "az", "containerapp", "create",
                "-g", resource_group, "-n", APP_NAME,
                "--environment", environment,
                "--image", image_ref,
                "--target-port", str(PORT),
                "--ingress", "external" if external else "internal",
                "--system-assigned",
                "--registry-server", registry,
                "--registry-identity", "system",
                "--min-replicas", "0",
                "--max-replicas", "3",
                "--env-vars", *env_vars,
            ],
            check=True,
        )

    # Grant the app's managed identity the data-plane roles it needs so the
    # server's DefaultAzureCredential can reach Azure AI Search and Azure OpenAI.
    principal_id = subprocess.run(
        [
            "az", "containerapp", "show",
            "-g", resource_group, "-n", APP_NAME,
            "--query", "identity.principalId", "-o", "tsv",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    if principal_id:
        acr_scope = _acr_id(registry_name)
        search_service = os.getenv("AZURE_AI_SEARCH_SERVICE_NAME", "")
        if search_service:
            search_scope = subprocess.run(
                [
                    "az", "search", "service", "show",
                    "--name", search_service, "-g", resource_group,
                    "--query", "id", "-o", "tsv",
                ],
                capture_output=True, text=True,
            ).stdout.strip()
            if search_scope:
                _assign_role(
                    principal_id, _SEARCH_INDEX_DATA_READER_ROLE_ID, search_scope,
                    "Search Index Data Reader",
                )
        # OpenAI data plane (embeddings) lives on the AI Services account.
        aoai_account_id = os.getenv("AZURE_AI_PROJECT_ID", "")
        if aoai_account_id and "/projects/" in aoai_account_id:
            account_scope = aoai_account_id.split("/projects/")[0]
            assign_cognitive_services_openai_user_role(principal_id, account_scope)
        # AcrPull is auto-assigned by `az containerapp create --registry-identity system`.
        _ = acr_scope
    else:
        print("  WARNING: no managed identity principal found — assign data-plane roles manually.")

    fqdn = subprocess.run(
        [
            "az", "containerapp", "show",
            "-g", resource_group, "-n", APP_NAME,
            "--query", "properties.configuration.ingress.fqdn", "-o", "tsv",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    if fqdn:
        mcp_url = f"https://{fqdn}{os.getenv('RESEARCH_MCP_PATH', '/mcp')}"
        print(f"\n✅ Research MCP server deployed: {mcp_url}")
        print(f"   Health probe: https://{fqdn}/health")
    else:
        print(
            "\n✅ Research MCP server deployed, but no ingress FQDN was returned. "
            "Set RESEARCH_MCP_EXTERNAL=true or check the Container App ingress."
        )


if __name__ == "__main__":
    do_build = "--build" in sys.argv
    built_tag: str | None = None
    if do_build:
        built_tag = build()
    deploy(tag=built_tag)
