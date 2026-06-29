"""Build the ingestion-agent container and provision its managed identity.

Two responsibilities:

  1. **Remote-build** the ingestion-agent image in Azure Container Registry
     (ACR Tasks — no local Docker daemon needed). The build context is the repo
     root and the Dockerfile bakes the agent + skills + deps into the image.

  2. **Provision a user-assigned managed identity** (always the same name) and
     grant it everything the agent needs at runtime so it can authenticate with
     zero secrets from inside a sandbox:
       * Cognitive Services OpenAI User  — call Foundry models (chat + embeddings)
       * Azure AI User                   — access the Foundry project
       * Search Index Data Contributor   — upsert documents into the index
       * Search Service Contributor      — create/update the index definition
       * AcrPull                         — pull the image when it's converted into
                                           a sandbox disk image

The launcher ``scripts/run_ingestion_sandbox.py`` reuses this same identity.

Usage::

    python scripts/build_ingestion_image.py            # build + provision identity
    python scripts/build_ingestion_image.py --no-build # provision/refresh identity only

Environment variables (populated by ``azd up`` into ``./.env``):
  AZURE_CONTAINER_REGISTRY_ENDPOINT   ACR login server, e.g. myacr.azurecr.io  (required)
  AZURE_AI_PROJECT_ID                  Foundry project ARM id                   (required)
  AZURE_AI_SEARCH_ENDPOINT            Azure AI Search endpoint                  (required)
  AZURE_AI_SEARCH_SERVICE_NAME        Search service name (else derived from endpoint)
  RESOURCE_GROUP_NAME                 sandbox RG for the identity (default: aca-sandboxes-rg)
  AZURE_RESOURCE_GROUP                 infra RG for Search (else derived from project id)
  LOCATION                            region for a new identity (default: westus3)
  INGESTION_IDENTITY_NAME             UAMI name (default: ingestion-agent-identity)
  INGESTION_IMAGE_NAME                image repository (default: ingestion-agent)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

# Allow running directly: python scripts/build_ingestion_image.py
sys.path.insert(0, str(Path(__file__).parent))

from deploy_helpers import (  # noqa: E402
    _assign_role,
    account_scope_from_project_id,
    assign_azure_ai_user_role,
    assign_cognitive_services_openai_user_role,
    get_env,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DOCKERFILE = "src/agents/ingestion/Dockerfile"

IMAGE_NAME = os.getenv("INGESTION_IMAGE_NAME", "ingestion-agent")
IDENTITY_NAME = os.getenv("INGESTION_IDENTITY_NAME", "ingestion-agent-identity")
LOCATION = os.getenv("LOCATION", "westus3")

# The managed identity lives in the **sandbox** resource group so the launcher
# (run_ingestion_sandbox.py) resolves the same identity by name.
SANDBOX_RG = os.getenv("RESOURCE_GROUP_NAME", "aca-sandboxes-rg")

# Built-in Azure role definition IDs.
_SEARCH_INDEX_DATA_CONTRIBUTOR = "8ebe5a00-799e-43f5-93ac-243d3dce84a7"
_SEARCH_SERVICE_CONTRIBUTOR = "7ca78c08-252a-4471-8644-bb5ff32d4ba0"
_ACR_PULL = "7f951dda-4ed3-4680-a7ca-43fe172d538d"


def _registry_name(login_server: str) -> str:
    return login_server.split(".")[0]


def _infra_resource_group() -> str:
    """Resource group hosting the Foundry / Search / ACR resources.

    Prefers an explicit ``AZURE_RESOURCE_GROUP`` but falls back to parsing it out
    of the Foundry project ARM id (``/resourceGroups/<rg>/``).
    """
    explicit = os.getenv("AZURE_RESOURCE_GROUP", "").strip()
    if explicit:
        return explicit
    project_id = get_env("AZURE_AI_PROJECT_ID")
    marker = "/resourceGroups/"
    idx = project_id.lower().find(marker.lower())
    if idx == -1:
        raise RuntimeError(
            "Cannot derive the infrastructure resource group: set AZURE_RESOURCE_GROUP "
            "or ensure AZURE_AI_PROJECT_ID contains '/resourceGroups/<rg>/'."
        )
    return project_id[idx + len(marker):].split("/")[0]


def _az_json(cmd: list[str]) -> dict:
    out = subprocess.run(cmd, check=True, capture_output=True, text=True).stdout
    return json.loads(out)


def build() -> str:
    """Remote-build the image with a timestamped tag **and** :latest."""
    registry = get_env("AZURE_CONTAINER_REGISTRY_ENDPOINT")
    registry_name = _registry_name(registry)
    build_tag = datetime.now().strftime("%Y%m%d%H%M%S")

    print(f"🏗️  Remote-building {registry}/{IMAGE_NAME}:{build_tag} (also :latest)")
    print(f"   registry: {registry_name}")
    print(f"   context:  {_REPO_ROOT}")
    print("   (runs in the cloud via ACR Tasks — no local Docker needed)\n")

    subprocess.run(
        [
            "az", "acr", "build",
            "--registry", registry_name,
            "--image", f"{IMAGE_NAME}:{build_tag}",
            "--image", f"{IMAGE_NAME}:latest",
            "--platform", "linux/amd64",
            "--file", str(Path(_DOCKERFILE)),
            str(_REPO_ROOT),
        ],
        check=True,
    )
    print(f"\n✅ Built and pushed: {registry}/{IMAGE_NAME}:{build_tag}")
    return build_tag


def _resolve_identity() -> tuple[str, str, str]:
    """Create or reuse the user-assigned managed identity.

    Lives in the sandbox resource group (``RESOURCE_GROUP_NAME``) so the launcher
    finds the same identity. The RG is created if it does not exist yet.

    Returns (resource_id, client_id, principal_id).
    """
    rg = SANDBOX_RG
    subprocess.run(
        ["az", "group", "create", "-n", rg, "-l", LOCATION, "-o", "none"], check=True
    )
    show = subprocess.run(
        ["az", "identity", "show", "-g", rg, "-n", IDENTITY_NAME, "-o", "json"],
        capture_output=True, text=True,
    )
    if show.returncode == 0:
        data = json.loads(show.stdout)
        print(f"  ♻️  Using existing identity: {IDENTITY_NAME} (rg={rg})")
    else:
        data = _az_json(
            ["az", "identity", "create", "-g", rg, "-n", IDENTITY_NAME, "-l", LOCATION, "-o", "json"]
        )
        print(f"  ✅ Created identity: {IDENTITY_NAME} (rg={rg})")
    return data["id"], data["clientId"], data["principalId"]


def _search_service_scope() -> str:
    """Resolve the Azure AI Search service ARM id from env."""
    rg = _infra_resource_group()
    service = os.getenv("AZURE_AI_SEARCH_SERVICE_NAME", "").strip()
    if not service:
        endpoint = get_env("AZURE_AI_SEARCH_ENDPOINT")
        service = urlparse(endpoint).netloc.split(".")[0]
    return _az_json(
        ["az", "search", "service", "show", "--name", service, "-g", rg, "-o", "json"]
    )["id"]


def _acr_scope() -> str:
    registry_name = _registry_name(get_env("AZURE_CONTAINER_REGISTRY_ENDPOINT"))
    return _az_json(["az", "acr", "show", "--name", registry_name, "-o", "json"])["id"]


def provision_identity() -> None:
    print("\n### Provisioning user-assigned managed identity + roles")
    _, client_id, principal_id = _resolve_identity()
    print(f"  🔑 clientId:    {client_id}")
    print(f"  🪪 principalId: {principal_id}")

    project_id = get_env("AZURE_AI_PROJECT_ID")
    account_scope = account_scope_from_project_id(project_id)

    print("\n  → Foundry models (chat + embeddings)")
    assign_cognitive_services_openai_user_role(principal_id, account_scope)
    print("  → Foundry project access")
    assign_azure_ai_user_role(principal_id, project_id)

    print("\n  → Azure AI Search (data plane + index management)")
    search_scope = _search_service_scope()
    _assign_role(principal_id, _SEARCH_INDEX_DATA_CONTRIBUTOR, search_scope, "Search Index Data Contributor")
    _assign_role(principal_id, _SEARCH_SERVICE_CONTRIBUTOR, search_scope, "Search Service Contributor")

    print("\n  → ACR pull (for sandbox disk-image conversion)")
    _assign_role(principal_id, _ACR_PULL, _acr_scope(), "AcrPull")

    print("\n✅ Identity provisioned. The launcher reuses it by name:")
    print(f"     INGESTION_IDENTITY_NAME={IDENTITY_NAME}")


def main() -> int:
    do_build = "--no-build" not in sys.argv
    if do_build:
        build()
    else:
        print("⏭️  Skipping image build (--no-build).")
    provision_identity()
    print("\nNext: launch a sandbox per URL with")
    print("     python scripts/run_ingestion_sandbox.py --url <url>")
    print("     python scripts/run_ingestion_sandbox.py --urls-file data/query-samples.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
