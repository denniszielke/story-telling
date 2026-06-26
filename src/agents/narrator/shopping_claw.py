"""
Shopping Claw — an OpenClaw agent that runs ONLY inside an Azure Container Apps
Sandbox and exposes its canvas + A2UI surfaces through the OpenClaw gateway.

OpenClaw is never installed or executed on the operator's machine. Instead a
custom "bring-your-own-container" image (see ./Dockerfile) bakes OpenClaw + the
shopping-claw skill into a disk image. This script:

  1. ensures the resource group + sandbox group + data-plane role exist,
  2. mints a short-lived ACR token and converts the pushed image into a
     private sandbox disk image,
  3. boots a sandbox from that disk image,
  4. starts the OpenClaw gateway *inside the sandbox* (bound to 0.0.0.0:18789),
  5. exposes the gateway port publicly via the sandbox ingress, and
  6. verifies + prints the public canvas and A2UI URLs:
        https://<host>/__openclaw__/canvas/
        https://<host>/__openclaw__/a2ui/

Build the image first (remote build in ACR, no local Docker):

    python scripts/build_narrator_image.py

Then run this orchestrator:

    python src/agents/narrator/shopping_claw.py

Configuration (.env or environment variables):
  AZURE_CONTAINER_REGISTRY_ENDPOINT   ACR login server, e.g. myacr.azurecr.io   (required)
  NARRATOR_IMAGE_TAG                   image:tag to boot      (default: shopping-claw:latest)
  RESOURCE_GROUP_NAME                  Azure resource group   (default: aca-sandboxes-rg)
  SANDBOX_GROUP_NAME                   sandbox group name     (default: shopping-claw)
  LOCATION                            Azure region            (default: westus3)
  OPENCLAW_PROVIDER                    model provider id      (default: openai)
  OPENCLAW_PROVIDER_API_KEY_ENV        env var name the provider key lives in    (default: OPENAI_API_KEY)
  OPENCLAW_MODEL                       default model           (default: gpt-5.4)
  OPENCLAW_GATEWAY_AUTH_MODE           token | none            (default: token)
"""

from __future__ import annotations

import os
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from azure.containerapps.sandbox import (
    RegistryCredentials,
    SandboxGroupClient,
    SandboxGroupManagementClient,
    endpoint_for_region,
)
from azure.core.exceptions import ClientAuthenticationError
from azure.identity import AzureCliCredential
from azure.mgmt.authorization import AuthorizationManagementClient
from azure.mgmt.resource.resources import ResourceManagementClient
from dotenv import load_dotenv
import json

# ── Load configuration ───────────────────────────────────────────────────────
_env_file = Path(__file__).resolve().parents[3] / ".env"
load_dotenv(_env_file, override=True)

ACR_ENDPOINT = os.getenv("AZURE_CONTAINER_REGISTRY_ENDPOINT", "")
if not ACR_ENDPOINT:
    sys.exit(
        "❌ AZURE_CONTAINER_REGISTRY_ENDPOINT is not set (e.g. 'myacr.azurecr.io').\n"
        "   Build the image first: python scripts/build_narrator_image.py"
    )
ACR_NAME = ACR_ENDPOINT.split(".")[0]

IMAGE_TAG = os.getenv("NARRATOR_IMAGE_TAG", "shopping-claw:latest")
IMAGE_REF = f"{ACR_ENDPOINT}/{IMAGE_TAG}"

RESOURCE_GROUP_NAME = os.getenv("RESOURCE_GROUP_NAME", "aca-sandboxes-rg")
SANDBOX_GROUP_NAME = os.getenv("SANDBOX_GROUP_NAME", "shopping-claw")
LOCATION = os.getenv("LOCATION", "westus3")

GATEWAY_PORT = int(os.getenv("OPENCLAW_GATEWAY_PORT", "18789"))
AUTH_MODE = os.getenv("OPENCLAW_GATEWAY_AUTH_MODE", "token")
MODEL = os.getenv("OPENCLAW_MODEL", "gpt-5.4")
PROVIDER = os.getenv("OPENCLAW_PROVIDER", "openai")
PROVIDER_KEY_ENV = os.getenv("OPENCLAW_PROVIDER_API_KEY_ENV", "OPENAI_API_KEY")
PROVIDER_KEY = os.getenv(PROVIDER_KEY_ENV, "")

# -- User-assigned managed identity (UAMI) ------------------------------------
# The agent authenticates to Azure through a user-assigned managed identity:
#   - the sandbox group runs as this identity,
#   - the disk image is pulled from ACR with this identity (AcrPull),
#   - code/agent inside the sandbox uses it via AZURE_CLIENT_ID (zero secrets).
# Provide an existing identity by resource id, or let the script create one.
MANAGED_IDENTITY_RESOURCE_ID = os.getenv("AZURE_MANAGED_IDENTITY_RESOURCE_ID", "")
MANAGED_IDENTITY_NAME = os.getenv("MANAGED_IDENTITY_NAME", "shopping-claw-identity")

# When set, the OpenClaw model provider is Azure OpenAI reached via the UAMI
# (AAD token), so no model API key is needed.
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "")
# ARM resource id of the Azure OpenAI / AI Services account, used to grant the
# UAMI the "Cognitive Services OpenAI User" role. Optional.
AZURE_OPENAI_ACCOUNT_ID = os.getenv("AZURE_OPENAI_ACCOUNT_ID", "")

# Built-in Azure role definition GUIDs.
_ACR_PULL_ROLE_ID = "7f951dda-4ed3-4680-a7ca-43fe172d538d"
_AOAI_USER_ROLE_ID = "5e0bd9bd-7b93-4f28-af87-19fc36ad61bd"

CANVAS_PATH = "/__openclaw__/canvas/"
A2UI_PATH = "/__openclaw__/a2ui/"

run_id = uuid.uuid4().hex[:8]
lab_labels = {"scenario": "shopping-claw", "run": run_id}

# A shared-secret gateway token for public ingress (unless auth disabled).
GATEWAY_TOKEN = "" if AUTH_MODE == "none" else secrets.token_urlsafe(24)

# Make unicode prints work on cp1252 terminals.
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")


# ── Helpers ──────────────────────────────────────────────────────────────────
def _exec_check(sandbox, cmd: str, *, label: str = "") -> str:
    r = sandbox.exec(cmd)
    if r.exit_code != 0:
        tag = f" [{label}]" if label else ""
        raise RuntimeError(
            f"sandbox exec failed{tag}: exit={r.exit_code}\n"
            f"  cmd : {cmd!r}\n"
            f"  out : {(r.stdout or '')[:400]}\n"
            f"  err : {(r.stderr or '')[:400]}"
        )
    return (r.stdout or "").strip()


def _wait_exec_up(sandbox, *, timeout: float = 120.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if sandbox.exec("true").exit_code == 0:
                return
        except Exception:
            pass
        time.sleep(2)
    raise RuntimeError("sandbox exec endpoint did not come up in time")


def _with_token(url: str) -> str:
    """Append the gateway token as a query param when token auth is on."""
    if not GATEWAY_TOKEN:
        return url
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}token={GATEWAY_TOKEN}"


def _poll_gateway_in_sandbox(sandbox, *, timeout_s: int = 120) -> None:
    """curl the canvas host from inside the sandbox until the HTTP server answers."""
    deadline = time.monotonic() + timeout_s
    url = _with_token(f"http://localhost:{GATEWAY_PORT}{CANVAS_PATH}")
    cmd = f"curl -fsS -o /dev/null -w '%{{http_code}}' '{url}' 2>/dev/null || true"
    last = ""
    while time.monotonic() < deadline:
        r = sandbox.exec(cmd)
        last = (r.stdout or "").strip()
        # Any HTTP status (200/3xx/401) means the gateway HTTP server is listening.
        if last.isdigit() and last != "000":
            return
        time.sleep(2)
    log = sandbox.exec("tail -60 /tmp/openclaw.log 2>/dev/null || true")
    raise RuntimeError(
        f"OpenClaw gateway did not answer on {CANVAS_PATH} after {timeout_s}s "
        f"(last http_code={last!r}).\n"
        f"gateway log:\n{(log.stdout or '').strip()}"
    )


def _verify_public(url: str, *, timeout_s: int = 90) -> int:
    """GET a public URL until it responds; return the final HTTP status."""
    deadline = time.monotonic() + timeout_s
    last_err = ""
    while time.monotonic() < deadline:
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=15) as resp:
                return resp.status
        except urllib.error.HTTPError as e:
            # An HTTP error status still proves the endpoint is reachable.
            return e.code
        except urllib.error.URLError as e:
            last_err = f"urlerror {e.reason}"
        time.sleep(3)
    raise RuntimeError(f"public URL not reachable after {timeout_s}s (last: {last_err})")


def _portal_url(sub: str, sandbox_id: str) -> str:
    return (
        f"https://sandboxes.azure.com/sandbox-groups/{sub}/{RESOURCE_GROUP_NAME}"
        f"/{SANDBOX_GROUP_NAME}/sandboxes/{sandbox_id}"
    )


def _az_json(cmd: str) -> dict:
    proc = subprocess.run(cmd, capture_output=True, text=True, check=True, shell=True)
    return json.loads(proc.stdout)


def _resolve_managed_identity() -> tuple[str, str, str]:
    """Resolve (or create) the user-assigned managed identity.

    Returns (resource_id, client_id, principal_id).
    """
    if MANAGED_IDENTITY_RESOURCE_ID:
        data = _az_json(f"az identity show --ids {MANAGED_IDENTITY_RESOURCE_ID} -o json")
    else:
        show = subprocess.run(
            f"az identity show -g {RESOURCE_GROUP_NAME} -n {MANAGED_IDENTITY_NAME} -o json",
            capture_output=True, text=True, shell=True,
        )
        if show.returncode == 0:
            data = json.loads(show.stdout)
            print(f"  ♻️  Using existing identity: {MANAGED_IDENTITY_NAME}")
        else:
            data = _az_json(
                f"az identity create -g {RESOURCE_GROUP_NAME} -n {MANAGED_IDENTITY_NAME} "
                f"-l {LOCATION} -o json"
            )
            print(f"  ✅ Created identity: {MANAGED_IDENTITY_NAME}")
    return data["id"], data["clientId"], data["principalId"]


def _assign_role(
    auth_client: AuthorizationManagementClient,
    subscription_id: str,
    principal_id: str,
    role_definition_id: str,
    scope: str,
    role_name: str,
) -> None:
    """Assign a role to a principal at a scope. Idempotent.

    `role_definition_id` may be a bare GUID or a full ARM role-definition id.
    """
    if "/" not in role_definition_id:
        role_definition_id = (
            f"/subscriptions/{subscription_id}/providers/Microsoft.Authorization"
            f"/roleDefinitions/{role_definition_id}"
        )
    try:
        auth_client.role_assignments.create(scope, uuid.uuid4(), {
            "role_definition_id": role_definition_id,
            "principal_id": principal_id,
            "principal_type": "ServicePrincipal",
        })
        print(f"  ✅ Assigned '{role_name}' to the managed identity")
    except Exception as ex:
        if "RoleAssignmentExists" in str(ex) or "Conflict" in str(ex):
            print(f"  ♻️  '{role_name}' already assigned to the managed identity")
        else:
            raise


def _build_openclaw_config(gateway_token: str) -> str:
    """Build the OpenClaw gateway config as JSON.

    When AZURE_OPENAI_ENDPOINT is set the model provider is Azure OpenAI reached
    via the user-assigned managed identity (no API key). Otherwise it falls back
    to a key-based provider.
    """
    if AZURE_OPENAI_ENDPOINT:
        default_provider = "azure-openai"
        providers = {
            "azure-openai": {
                "endpoint": AZURE_OPENAI_ENDPOINT,
                # Authenticate with the UAMI (AZURE_CLIENT_ID) instead of a key.
                "auth": "managed-identity",
            }
        }
    else:
        default_provider = PROVIDER
        providers = {PROVIDER: {"apiKeyEnv": PROVIDER_KEY_ENV}}

    config = {
        "gateway": {
            "bind": {"host": "0.0.0.0", "port": GATEWAY_PORT},
            "auth": {"mode": AUTH_MODE, "token": gateway_token},
        },
        "models": {"default": f"{default_provider}/{MODEL}", "providers": providers},
        "agents": {"defaults": {"skills": ["/opt/shopping-claw/skills/shopping"]}},
    }
    return json.dumps(config, indent=2)


def _create_disk_image(client, mi_resource_id: str, *, attempts: int = 6, wait_s: int = 30):
    """Create the private disk image, pulling the BYOC image with the UAMI.

    A freshly-assigned AcrPull role can take a few minutes to propagate, so the
    initial pulls may return 401. We retry on auth failures and, as a last
    resort, fall back to a short-lived ACR token so a brand-new role assignment
    never blocks the run.
    """
    name = f"shopping-claw-{run_id}"
    for attempt in range(1, attempts + 1):
        try:
            return client.begin_create_disk_image(
                IMAGE_REF,
                name=name,
                managed_identity_resource_id=mi_resource_id,
                polling_timeout=900,
            ).result()
        except ClientAuthenticationError:
            if attempt == attempts:
                break
            print(f"  ⏳ identity pull not ready (attempt {attempt}/{attempts}); "
                  f"AcrPull still propagating — waiting {wait_s}s...")
            time.sleep(wait_s)

    print("  ⚠️  Managed-identity pull still failing; falling back to a "
          "short-lived ACR token for the image pull.")
    token = _az_json(f"az acr login --name {ACR_NAME} --expose-token -o json")["accessToken"]
    creds = RegistryCredentials(
        username="00000000-0000-0000-0000-000000000000", token=token,
    )
    return client.begin_create_disk_image(
        IMAGE_REF,
        name=name,
        registry_credentials=creds,
        polling_timeout=900,
    ).result()


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> int:
    if not AZURE_OPENAI_ENDPOINT and not PROVIDER_KEY:
        print(
            f"⚠️  Neither AZURE_OPENAI_ENDPOINT nor {PROVIDER_KEY_ENV} is set — the "
            f"gateway will start but the agent can't call a model until one is "
            f"provided. Set AZURE_OPENAI_ENDPOINT to use the managed identity."
        )

    # -- Azure subscription info -----------------------------------------------
    try:
        proc = subprocess.run(
            "az account show -o json",
            capture_output=True, text=True, check=True, shell=True,
        )
        subscription = json.loads(proc.stdout)
        subscription_id = subscription["id"]
    except subprocess.CalledProcessError as e:
        sys.exit(f"❌ az CLI not logged in. Run `az login` first.\n{e.stderr}")

    print(f"🦞 Scenario:              shopping-claw  (run={run_id})")
    print(f"👤 User:                  {subscription['user']['name']}")
    print(f"🔑 Subscription:          {subscription['name']} ({subscription_id})")
    print(f"🌍 Region:                {LOCATION}")
    print(f"📁 Resource group:        {RESOURCE_GROUP_NAME}")
    print(f"📦 Sandbox group:         {SANDBOX_GROUP_NAME}")
    print(f"🖼️  BYOC image:            {IMAGE_REF}")
    print(f"🔌 Gateway port:          {GATEWAY_PORT}  (auth: {AUTH_MODE})")

    cli_credential = AzureCliCredential()
    resource_mgmt_client = ResourceManagementClient(cli_credential, subscription_id)
    sandboxgroup_mgmt_client = SandboxGroupManagementClient(
        cli_credential,
        subscription_id=subscription_id,
        resource_group=RESOURCE_GROUP_NAME,
    )
    auth_client = AuthorizationManagementClient(cli_credential, subscription_id)

    # -- Resource group --------------------------------------------------------
    print("\n### Step 1: Resource group + user-assigned identity")
    if resource_mgmt_client.resource_groups.check_existence(RESOURCE_GROUP_NAME):
        rg = resource_mgmt_client.resource_groups.get(RESOURCE_GROUP_NAME)
        print(f"♻️  Using existing RG: {rg.name} ({rg.location})")
    else:
        rg = resource_mgmt_client.resource_groups.create_or_update(
            RESOURCE_GROUP_NAME, {"location": LOCATION, "tags": lab_labels}
        )
        print(f"✅ Created RG: {rg.name} ({rg.location})")

    # Resolve (or create) the user-assigned managed identity the agent runs as.
    mi_resource_id, mi_client_id, mi_principal_id = _resolve_managed_identity()
    print(f"  🪪 Identity resourceId: {mi_resource_id}")
    print(f"  🔑 Identity clientId:   {mi_client_id}")

    # -- Sandbox group (assigned the user-assigned identity) -------------------
    group_identity = {
        "type": "UserAssigned",
        "userAssignedIdentities": {mi_resource_id: {}},
    }
    existing = next(
        (g for g in sandboxgroup_mgmt_client.list_groups() if g.name == SANDBOX_GROUP_NAME),
        None,
    )
    # create_or_update semantics — also (re)attaches the identity to an existing group.
    sandboxgroup_mgmt_client.begin_create_group(
        SANDBOX_GROUP_NAME,
        location=rg.location,
        identity=group_identity,
        tags=lab_labels,
    ).result()
    print(f"{'♻️  Updated' if existing else '✅ Created'} sandbox group "
          f"'{SANDBOX_GROUP_NAME}' with user-assigned identity")

    sandboxgroup = sandboxgroup_mgmt_client.get_group(SANDBOX_GROUP_NAME)

    # -- Role assignments ------------------------------------------------------
    print("\n### Step 2: Role assignments")
    rg_scope = f"/subscriptions/{subscription_id}/resourceGroups/{RESOURCE_GROUP_NAME}"
    data_owner_role = "Container Apps SandboxGroup Data Owner"
    data_owner_def = next(
        auth_client.role_definitions.list(rg_scope, filter=f"roleName eq '{data_owner_role}'")
    )

    # (a) The signed-in user needs the data-plane role to create sandboxes.
    proc = subprocess.run(
        "az ad signed-in-user show --query id -o tsv",
        capture_output=True, text=True, check=True, shell=True,
    )
    user_principal_id = proc.stdout.strip()
    try:
        auth_client.role_assignments.create(rg_scope, uuid.uuid4(), {
            "role_definition_id": data_owner_def.id,
            "principal_id": user_principal_id,
            "principal_type": "User",
        })
        print(f"  ✅ Assigned '{data_owner_role}' to you")
    except Exception as ex:
        if "RoleAssignmentExists" in str(ex) or "Conflict" in str(ex):
            print(f"  ♻️  '{data_owner_role}' already assigned to you")
        else:
            raise

    # (b) The managed identity needs AcrPull (to pull the BYOC image) and the
    #     data-plane role (so the agent could manage sibling sandboxes).
    acr_resource_id = _az_json(f"az acr show -n {ACR_NAME} -o json")["id"]
    _assign_role(auth_client, subscription_id, mi_principal_id,
                 _ACR_PULL_ROLE_ID, acr_resource_id, "AcrPull")
    _assign_role(auth_client, subscription_id, mi_principal_id,
                 data_owner_def.id, rg_scope, data_owner_role)

    # (c) Optionally let the identity call Azure OpenAI directly (no model key).
    if AZURE_OPENAI_ACCOUNT_ID:
        _assign_role(auth_client, subscription_id, mi_principal_id,
                     _AOAI_USER_ROLE_ID, AZURE_OPENAI_ACCOUNT_ID,
                     "Cognitive Services OpenAI User")

    print("  ⏳ Waiting 60s for role propagation...")
    time.sleep(60)

    # -- Data-plane client -----------------------------------------------------
    client = SandboxGroupClient(
        endpoint_for_region(sandboxgroup.location),
        cli_credential,
        subscription_id=subscription_id,
        resource_group=RESOURCE_GROUP_NAME,
        sandbox_group=SANDBOX_GROUP_NAME,
    )

    # -- Private disk image (pulled with the managed identity) -----------------
    print("\n### Step 3: Convert ACR image → private disk image (via identity)")
    disk_image = _create_disk_image(client, mi_resource_id)
    print(f"  💾 Disk image ready: {disk_image.id}")

    sandbox = None
    port_added = False
    try:
        # -- Boot sandbox from the custom image --------------------------------
        print("\n### Step 4: Boot sandbox from BYOC image")
        # Seed Azure identity env so the agent inside authenticates as the UAMI
        # (ManagedIdentityCredential / DefaultAzureCredential pick up AZURE_CLIENT_ID).
        sandbox_env = {
            "AZURE_CLIENT_ID": mi_client_id,
            "AZURE_SUBSCRIPTION_ID": subscription_id,
            "ACA_RESOURCE_GROUP": RESOURCE_GROUP_NAME,
            "ACA_SANDBOX_GROUP": SANDBOX_GROUP_NAME,
            "ACA_SANDBOXGROUP_REGION": sandboxgroup.location,
        }
        if AZURE_OPENAI_ENDPOINT:
            sandbox_env["AZURE_OPENAI_ENDPOINT"] = AZURE_OPENAI_ENDPOINT
        elif PROVIDER_KEY:
            sandbox_env[PROVIDER_KEY_ENV] = PROVIDER_KEY

        sandbox = client.begin_create_sandbox(
            disk_id=disk_image.id,
            cpu="2000m",
            memory="4096Mi",
            labels=lab_labels,
            environment=sandbox_env,
        ).result()
        print(f"✅ Sandbox ready: {sandbox.sandbox_id}")
        print(f"   Portal: {_portal_url(subscription_id, sandbox.sandbox_id)}")
        print(f"   🪪 Agent identity (AZURE_CLIENT_ID): {mi_client_id}")
        print("⏳ Waiting for exec endpoint...")
        _wait_exec_up(sandbox)

        # Prove the custom image booted: OpenClaw is baked in, not on the host.
        oc_version = _exec_check(sandbox, "openclaw --version", label="openclaw-version")
        print(f"  🦞 OpenClaw in sandbox: {oc_version}")

        # -- Start the gateway INSIDE the sandbox ------------------------------
        print("\n### Step 5: Start OpenClaw gateway (inside sandbox)")
        # Write a fully-rendered config (managed-identity aware) directly into the
        # sandbox — no fragile template substitution.
        config_json = _build_openclaw_config(GATEWAY_TOKEN)
        _exec_check(sandbox, "mkdir -p /root/.openclaw", label="config-dir")
        sandbox.write_file("/root/.openclaw/openclaw.json", config_json)
        provider_label = "azure-openai (managed identity)" if AZURE_OPENAI_ENDPOINT else PROVIDER
        print(f"  📝 Wrote gateway config (provider: {provider_label})")

        sandbox.exec(
            "cd /root && nohup openclaw gateway "
            "> /tmp/openclaw.log 2>&1 & echo $! > /tmp/openclaw.pid"
        )
        print(f"  ⏳ Waiting for the gateway HTTP server on :{GATEWAY_PORT}...")
        _poll_gateway_in_sandbox(sandbox)
        print("  ✅ Gateway is serving the canvas + A2UI hosts")

        # -- Expose the gateway port publicly ----------------------------------
        print("\n### Step 6: Expose the gateway publicly")
        port = sandbox.add_port(GATEWAY_PORT, anonymous=True)
        port_added = True
        public_url = getattr(port, "url", None)
        if not public_url:
            raise RuntimeError("add_port did not return a URL")
        base = public_url.rstrip("/")
        canvas_url = _with_token(base + CANVAS_PATH)
        a2ui_url = _with_token(base + A2UI_PATH)
        print(f"  🌐 base:   {base}")

        # -- Verify the public surfaces ----------------------------------------
        print("\n### Step 7: Verify public canvas + A2UI")
        canvas_status = _verify_public(canvas_url)
        a2ui_status = _verify_public(a2ui_url)
        print(f"  ✅ canvas → HTTP {canvas_status}")
        print(f"  ✅ a2ui   → HTTP {a2ui_status}")

        # -- Connection instructions -------------------------------------------
        print()
        print("=" * 72)
        print("SHOPPING CLAW DEPLOYED 🦞🛒")
        print("=" * 72)
        print()
        print("OpenClaw is running ONLY inside the sandbox. Open the surfaces:")
        print(f"  Canvas : {canvas_url}")
        print(f"  A2UI   : {a2ui_url}")
        if GATEWAY_TOKEN:
            print()
            print(f"  Gateway auth token: {GATEWAY_TOKEN}")
            print("  (sent as the ?token= query param above)")
        print("=" * 72)
        print()

        try:
            input("Press Enter to delete the sandbox when you're done… ")
        except (EOFError, KeyboardInterrupt):
            print()

    finally:
        # -- Cleanup -----------------------------------------------------------
        print("\n### Cleanup")
        if sandbox is not None and port_added:
            try:
                sandbox.remove_port(GATEWAY_PORT)
                print(f"  🔌 Removed port {GATEWAY_PORT}")
            except Exception as e:
                print(f"  ⚠️  remove_port failed: {e}")
        if sandbox is not None:
            try:
                client.delete_sandbox(sandbox.sandbox_id)
                print(f"  🗑️  Deleted sandbox {sandbox.sandbox_id}")
            except Exception as e:
                print(f"  ⚠️  delete failed: {e}")
        try:
            client.close()
        except Exception:
            pass
        try:
            cli_credential.close()
        except Exception:
            pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
