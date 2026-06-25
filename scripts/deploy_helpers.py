"""Shared helpers for agent deployment scripts."""

import json
import os
import subprocess
from datetime import datetime
from pathlib import Path

from azure.ai.projects import AIProjectClient
from azure.containerapps.sandbox import RegistryCredentials
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv

load_dotenv(override=True)

# Azure AI User role definition ID — required at project scope for hosted agent
# identities to call models and reach the toolbox MCP endpoint.
_AZURE_AI_USER_ROLE_ID = "53ca6127-db72-4b80-b1b0-d745d6d5456d"

# Cognitive Services OpenAI User role definition ID — required at the AI Services
# account scope so the agent identity can call the OpenAI data plane directly
# (chat/completions, embeddings).
_COGNITIVE_SERVICES_OPENAI_USER_ROLE_ID = "5e0bd9bd-7b93-4f28-af87-19fc36ad61bd"


def account_scope_from_project_id(project_arm_id: str) -> str:
    """Derive the parent Cognitive Services account ARM ID from a project ARM ID.

    A project ARM ID looks like
    ``/subscriptions/.../accounts/<account>/projects/<project>``; the account
    scope is everything up to (and including) the account segment.
    """
    marker = "/projects/"
    idx = project_arm_id.find(marker)
    return project_arm_id[:idx] if idx != -1 else project_arm_id


def get_env(name: str, required: bool = True, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if required and not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def get_client() -> AIProjectClient:
    return AIProjectClient(
        endpoint=get_env("AZURE_AI_PROJECT_ENDPOINT"),
        credential=DefaultAzureCredential(),
        allow_preview=True,
    )


def build_image(registry: str, agent_name: str, context_path: Path) -> str:
    """Build a container image on ACR and return the full image tag."""
    registry_name = registry.split(".")[0]
    build_tag = datetime.now().strftime("%Y%m%d%H%M%S")
    image_tag = f"{registry}/{agent_name}:{build_tag}"

    print(f"Queuing ACR build for {image_tag} from {context_path}...")
    subprocess.run(
        [
            "az", "acr", "build",
            "--registry", registry_name,
            "--image", image_tag,
            "--platform", "linux/amd64",
            str(context_path),
        ],
        check=True,
    )
    return image_tag


def get_registry_credentials(acr_name: str) -> RegistryCredentials:
    """Mint a short-lived ACR access token and return RegistryCredentials.

    Uses the current `az login` session via `--expose-token` to obtain an
    AAD-backed token. No admin user or stored secret required.
    """
    acr_login_server = f"{acr_name}.azurecr.io"
    proc = subprocess.run(
        f"az acr login --name {acr_name} --expose-token -o json",
        capture_output=True, text=True, check=True, shell=True,
    )
    acr_token = json.loads(proc.stdout)["accessToken"]
    print(f"\U0001f511 Obtained ACR access token for {acr_login_server} (length={len(acr_token)})")
    return RegistryCredentials(
        username="00000000-0000-0000-0000-000000000000", token=acr_token,
    )


def assign_azure_ai_user_role(principal_id: str, scope: str) -> None:
    """Assign the Azure AI User role to a principal at the given scope.

    Idempotent: ignores 'already exists' errors from az CLI.
    """
    _assign_role(principal_id, _AZURE_AI_USER_ROLE_ID, scope, "Azure AI User")


def assign_cognitive_services_openai_user_role(principal_id: str, scope: str) -> None:
    """Assign the Cognitive Services OpenAI User role at the given scope.

    Grants the OpenAI data-plane actions (chat/completions, embeddings) the
    agent needs when calling the model endpoint directly. Idempotent.
    """
    _assign_role(
        principal_id,
        _COGNITIVE_SERVICES_OPENAI_USER_ROLE_ID,
        scope,
        "Cognitive Services OpenAI User",
    )


def _assign_role(principal_id: str, role_id: str, scope: str, role_name: str) -> None:
    """Assign a role to a principal at a scope. Idempotent."""
    print(f"Assigning {role_name} role to principal {principal_id} at {scope}...")
    result = subprocess.run(
        [
            "az", "role", "assignment", "create",
            "--assignee-object-id", principal_id,
            "--assignee-principal-type", "ServicePrincipal",
            "--role", role_id,
            "--scope", scope,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        stderr = result.stderr or ""
        if "RoleAssignmentExists" in stderr or "already exists" in stderr.lower():
            print("  Role assignment already exists — skipping.")
            return
        raise RuntimeError(f"Role assignment failed: {stderr}")
