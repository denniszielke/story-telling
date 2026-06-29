"""Launch the ingestion agent inside Azure Container Apps Sandboxes.

The ingestion agent is **never** run on the operator's machine. This launcher
converts the ``ingestion-agent`` image (built by ``scripts/build_ingestion_image.py``)
into a private sandbox disk image and boots a sandbox **per URL**:

  * ``--url <single>``        → one sandbox processes that one URL.
  * ``--urls a,b,c``          → one sandbox **per URL** (same disk image, booted
                                sequentially).
  * ``--urls-file <json>``    → same, reading URLs from a JSON file.

Inside each sandbox the agent authenticates with the **same** user-assigned
managed identity (zero secrets) via ``AZURE_CLIENT_ID`` and runs:

    python -m src.agents.ingestion.ingestion_agent --url <url> [--objective <o>]

which classifies the URL with the asset-identification skill, runs the matching
processing skill, and upserts the result into Azure AI Search.

Usage::

    python scripts/run_ingestion_sandbox.py --url https://example.com/case-study
    python scripts/run_ingestion_sandbox.py --urls https://a.com,https://b.com
    python scripts/run_ingestion_sandbox.py --urls-file data/query-samples.json
    python scripts/run_ingestion_sandbox.py --url https://x.com --objective "use case"

Configuration (.env or environment):
  AZURE_CONTAINER_REGISTRY_ENDPOINT   ACR login server, e.g. myacr.azurecr.io   (required)
  AZURE_OPENAI_ENDPOINT               Foundry/AOAI endpoint                      (required)
  AZURE_AI_SEARCH_ENDPOINT           Azure AI Search endpoint                   (required)
  AZURE_AI_SEARCH_INDEX_NAME         target index name                          (required)
  AZURE_AI_PROJECT_ENDPOINT          Foundry project endpoint                   (optional)
  INGESTION_IMAGE_NAME               image repo  (default: ingestion-agent)
  INGESTION_IMAGE_TAG                image tag   (default: latest)
  INGESTION_IDENTITY_NAME            UAMI name   (default: ingestion-agent-identity)
  RESOURCE_GROUP_NAME                sandbox RG  (default: aca-sandboxes-rg)
  SANDBOX_GROUP_NAME                 group name  (default: ingestion-agent)
  LOCATION                           region      (default: westus3)
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

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

# ── Configuration ─────────────────────────────────────────────────────────────
_env_file = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(_env_file, override=True)

ACR_ENDPOINT = os.getenv("AZURE_CONTAINER_REGISTRY_ENDPOINT", "")
if not ACR_ENDPOINT:
    sys.exit(
        "❌ AZURE_CONTAINER_REGISTRY_ENDPOINT is not set (e.g. 'myacr.azurecr.io').\n"
        "   Build the image first: python scripts/build_ingestion_image.py"
    )
ACR_NAME = ACR_ENDPOINT.split(".")[0]

IMAGE_NAME = os.getenv("INGESTION_IMAGE_NAME", "ingestion-agent")
IMAGE_TAG = os.getenv("INGESTION_IMAGE_TAG", "latest")
IMAGE_REF = f"{ACR_ENDPOINT}/{IMAGE_NAME}:{IMAGE_TAG}"

RESOURCE_GROUP_NAME = os.getenv("RESOURCE_GROUP_NAME", "aca-sandboxes-rg")
SANDBOX_GROUP_NAME = os.getenv("SANDBOX_GROUP_NAME", "ingestion-agent")
LOCATION = os.getenv("LOCATION", "westus3")

MANAGED_IDENTITY_RESOURCE_ID = os.getenv("AZURE_MANAGED_IDENTITY_RESOURCE_ID", "")
MANAGED_IDENTITY_NAME = os.getenv("INGESTION_IDENTITY_NAME", "ingestion-agent-identity")

# Built-in Azure role definition GUIDs.
_ACR_PULL_ROLE_ID = "7f951dda-4ed3-4680-a7ca-43fe172d538d"

run_id = uuid.uuid4().hex[:8]
lab_labels = {"scenario": "ingestion-agent", "run": run_id}

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")


# ── URL parsing ───────────────────────────────────────────────────────────────
def _urls_from_file(path: str) -> list[str]:
    """Read URLs from a JSON file.

    Accepts: a list of strings, a list of objects with a 'url'/'source' key, or
    an object with a top-level 'urls' list.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("urls", data.get("items", []))
    urls: list[str] = []
    for item in data:
        if isinstance(item, str):
            urls.append(item.strip())
        elif isinstance(item, dict):
            value = item.get("url") or item.get("source") or item.get("reference")
            if value:
                urls.append(str(value).strip())
    return [u for u in urls if u]


def _collect_urls(args: argparse.Namespace) -> list[str]:
    if args.url:
        return [args.url.strip()]
    if args.urls:
        return [u.strip() for u in args.urls.split(",") if u.strip()]
    if args.urls_file:
        urls = _urls_from_file(args.urls_file)
        if not urls:
            sys.exit(f"❌ No URLs found in {args.urls_file}")
        return urls
    sys.exit("❌ Provide one of --url, --urls, or --urls-file.")


# ── Sandbox helpers ───────────────────────────────────────────────────────────
def _az_json(cmd: str) -> dict:
    proc = subprocess.run(cmd, capture_output=True, text=True, check=True, shell=True)
    return json.loads(proc.stdout)


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


def _exec_stream(sandbox, cmd: str, *, poll_interval: float = 3.0, label: str = "") -> int:
    """Run cmd in the background inside the sandbox and stream its output."""
    tag = uuid.uuid4().hex[:8]
    script_path = f"/tmp/stream_{tag}.sh"
    log_path = f"/tmp/stream_{tag}.log"
    done_path = f"/tmp/stream_{tag}.done"

    sandbox.write_file(script_path, f"#!/bin/bash\n{cmd}\n")
    sandbox.exec(f"chmod +x {script_path}")
    sandbox.exec(
        f"bash -c 'bash {script_path} >{log_path} 2>&1; echo $? >{done_path}' &"
    )

    lines_shown = 0
    while True:
        time.sleep(poll_interval)
        r = sandbox.exec(f"awk 'NR>{lines_shown}' {log_path} 2>/dev/null || true")
        if r.stdout:
            print(r.stdout, end="", flush=True)
            lines_shown += r.stdout.count("\n")
        done_r = sandbox.exec(f"cat {done_path} 2>/dev/null || true")
        exit_str = (done_r.stdout or "").strip()
        if exit_str and exit_str.lstrip("-").isdigit():
            r = sandbox.exec(f"awk 'NR>{lines_shown}' {log_path} 2>/dev/null || true")
            if r.stdout:
                print(r.stdout, end="", flush=True)
            return int(exit_str)


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
    *,
    principal_type: str = "ServicePrincipal",
) -> bool:
    """Assign a role to a principal at a scope. Idempotent.

    Returns True if a new assignment was created, False if it already existed.
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
            "principal_type": principal_type,
        })
        print(f"  ✅ Assigned '{role_name}'")
        return True
    except Exception as ex:
        if "RoleAssignmentExists" in str(ex) or "Conflict" in str(ex):
            print(f"  ♻️  '{role_name}' already assigned")
            return False
        raise


def _create_disk_image(client, mi_resource_id: str, *, attempts: int = 6, wait_s: int = 30):
    """Create the private disk image, pulling the BYOC image with the UAMI."""
    name = f"ingestion-agent-{run_id}"
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


def _sandbox_env(mi_client_id: str, subscription_id: str) -> dict[str, str]:
    """Environment injected into each sandbox so the agent runs zero-secret."""
    env = {
        # DefaultAzureCredential authenticates as the UAMI via AZURE_CLIENT_ID.
        "AZURE_CLIENT_ID": mi_client_id,
        "AZURE_SUBSCRIPTION_ID": subscription_id,
    }
    passthrough = [
        "AZURE_OPENAI_ENDPOINT",
        "AZURE_AI_SEARCH_ENDPOINT",
        "AZURE_AI_SEARCH_INDEX_NAME",
        "AZURE_AI_PROJECT_ENDPOINT",
        "AZURE_OPENAI_LARGE_CHAT_DEPLOYMENT_NAME",
        "OPENAI_API_VERSION",
        "AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME",
        "AZURE_OPENAI_EMBEDDING_DIMENSIONS",
        "AZURE_OPENAI_EMBEDDING_API_VERSION",
    ]
    for key in passthrough:
        value = os.getenv(key, "").strip()
        if value:
            env[key] = value
    return env


def _portal_url(sub: str, sandbox_id: str) -> str:
    return (
        f"https://sandboxes.azure.com/sandbox-groups/{sub}/{RESOURCE_GROUP_NAME}"
        f"/{SANDBOX_GROUP_NAME}/sandboxes/{sandbox_id}"
    )


def _egress_hosts_for_url(url: str) -> list[str]:
    """Host patterns that must be reachable to fetch the given URL.

    Returns the exact hostname plus a wildcard on its parent domain so that
    www↔apex and same-domain CDN/redirect subdomains are also covered.
    """
    host = (urlparse(url).hostname or "").strip().lower()
    if not host:
        return []
    hosts = {host}
    parts = host.split(".")
    if len(parts) > 2:
        hosts.add("*." + ".".join(parts[-2:]))
    return sorted(hosts)


def _allow_egress(sandbox, url: str) -> None:
    """Ensure the ingested URL's host is allowed through the sandbox egress."""
    for pattern in _egress_hosts_for_url(url):
        try:
            sandbox.add_egress_host_rule(pattern, action="Allow")
            print(f"  🌐 egress allow: {pattern}")
        except Exception as e:  # noqa: BLE001 - best-effort; default may already allow
            print(f"  ⚠️  could not add egress rule for {pattern}: {e}")


def _process_url(client, disk_id: str, sandbox_env: dict, url: str,
                 objective: str | None, subscription_id: str) -> int:
    """Boot a dedicated sandbox, run the agent against one URL, then delete it."""
    print(f"\n{'─' * 72}\n🌐 Ingesting: {url}\n{'─' * 72}")
    sandbox = None
    try:
        sandbox = client.begin_create_sandbox(
            disk_id=disk_id,
            cpu="1000m",
            memory="2048Mi",
            labels={**lab_labels, "url-hash": uuid.uuid5(uuid.NAMESPACE_URL, url).hex[:8]},
            environment=sandbox_env,
        ).result()
        print(f"  ✅ Sandbox: {sandbox.sandbox_id}")
        print(f"     Portal: {_portal_url(subscription_id, sandbox.sandbox_id)}")
        _wait_exec_up(sandbox)

        # Make sure the handed-in URL's host is reachable from the sandbox.
        _allow_egress(sandbox, url)

        # Build the agent command. Pass URL/objective via env to avoid quoting.
        cmd_env = f"export INGESTION_URL={json.dumps(url)}\n"
        agent_cmd = 'python -m src.agents.ingestion.ingestion_agent --url "$INGESTION_URL"'
        if objective:
            cmd_env += f"export INGESTION_OBJECTIVE={json.dumps(objective)}\n"
            agent_cmd += ' --objective "$INGESTION_OBJECTIVE"'

        exit_code = _exec_stream(
            sandbox, cmd_env + "cd /app\n" + agent_cmd,
            poll_interval=3.0, label="ingestion-agent",
        )
        if exit_code == 0:
            print(f"\n  ✅ Done: {url}")
        else:
            print(f"\n  ❌ Agent exited with code {exit_code} for {url}")
        return exit_code
    finally:
        if sandbox is not None:
            try:
                client.delete_sandbox(sandbox.sandbox_id)
                print(f"  🗑️  Deleted sandbox {sandbox.sandbox_id}")
            except Exception as e:
                print(f"  ⚠️  delete failed: {e}")


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> int:
    parser = argparse.ArgumentParser(description="Run the ingestion agent in sandboxes.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--url", help="A single URL to ingest.")
    group.add_argument("--urls", help="Comma-separated URLs (one sandbox per URL).")
    group.add_argument("--urls-file", help="JSON file of URLs (one sandbox per URL).")
    parser.add_argument(
        "--objective",
        choices=["use case", "code", "method"],
        help="Skip identification and force this objective.",
    )
    args = parser.parse_args()
    urls = _collect_urls(args)

    try:
        subscription = _az_json("az account show -o json")
        subscription_id = subscription["id"]
    except subprocess.CalledProcessError as e:
        sys.exit(f"❌ az CLI not logged in. Run `az login` first.\n{e}")

    print(f"📥 Scenario:        ingestion-agent  (run={run_id})")
    print(f"👤 User:            {subscription['user']['name']}")
    print(f"🔑 Subscription:    {subscription['name']} ({subscription_id})")
    print(f"🌍 Region:          {LOCATION}")
    print(f"📁 Resource group:  {RESOURCE_GROUP_NAME}")
    print(f"📦 Sandbox group:   {SANDBOX_GROUP_NAME}")
    print(f"🖼️  BYOC image:      {IMAGE_REF}")
    print(f"🔢 URLs to ingest:  {len(urls)}  (one sandbox each)")

    cli_credential = AzureCliCredential()
    resource_mgmt_client = ResourceManagementClient(cli_credential, subscription_id)
    sandboxgroup_mgmt_client = SandboxGroupManagementClient(
        cli_credential,
        subscription_id=subscription_id,
        resource_group=RESOURCE_GROUP_NAME,
    )
    auth_client = AuthorizationManagementClient(cli_credential, subscription_id)

    # -- Resource group + identity --------------------------------------------
    print("\n### Step 1: Resource group + user-assigned identity")
    if resource_mgmt_client.resource_groups.check_existence(RESOURCE_GROUP_NAME):
        rg = resource_mgmt_client.resource_groups.get(RESOURCE_GROUP_NAME)
        print(f"♻️  Using existing RG: {rg.name} ({rg.location})")
    else:
        rg = resource_mgmt_client.resource_groups.create_or_update(
            RESOURCE_GROUP_NAME, {"location": LOCATION, "tags": lab_labels}
        )
        print(f"✅ Created RG: {rg.name} ({rg.location})")

    mi_resource_id, mi_client_id, mi_principal_id = _resolve_managed_identity()
    print(f"  🪪 Identity resourceId: {mi_resource_id}")
    print(f"  🔑 Identity clientId:   {mi_client_id}")

    # -- Sandbox group with the identity attached -----------------------------
    group_identity = {
        "type": "UserAssigned",
        "userAssignedIdentities": {mi_resource_id: {}},
    }
    existing = next(
        (g for g in sandboxgroup_mgmt_client.list_groups() if g.name == SANDBOX_GROUP_NAME),
        None,
    )
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

    user_principal_id = subprocess.run(
        "az ad signed-in-user show --query id -o tsv",
        capture_output=True, text=True, check=True, shell=True,
    ).stdout.strip()
    new_data_owner = _assign_role(auth_client, subscription_id, user_principal_id,
                                  data_owner_def.id, rg_scope, data_owner_role, principal_type="User")

    acr_resource_id = _az_json(f"az acr show -n {ACR_NAME} -o json")["id"]
    new_acr_pull = _assign_role(auth_client, subscription_id, mi_principal_id,
                                _ACR_PULL_ROLE_ID, acr_resource_id, "AcrPull")

    # Only wait for propagation when something was actually assigned.
    if new_data_owner or new_acr_pull:
        print("  ⏳ Waiting 60s for role propagation...")
        time.sleep(60)
    else:
        print("  ✓ All roles already assigned — skipping propagation wait.")

    # -- Data-plane client + disk image ---------------------------------------
    client = SandboxGroupClient(
        endpoint_for_region(sandboxgroup.location),
        cli_credential,
        subscription_id=subscription_id,
        resource_group=RESOURCE_GROUP_NAME,
        sandbox_group=SANDBOX_GROUP_NAME,
    )

    print("\n### Step 3: Convert ACR image → private disk image (via identity)")
    disk_image = _create_disk_image(client, mi_resource_id)
    print(f"  💾 Disk image ready: {disk_image.id}")

    sandbox_env = _sandbox_env(mi_client_id, subscription_id)

    # -- One sandbox per URL ---------------------------------------------------
    print("\n### Step 4: Ingest URLs (one sandbox each)")
    failures = 0
    try:
        for url in urls:
            try:
                if _process_url(client, disk_image.id, sandbox_env, url,
                                args.objective, subscription_id) != 0:
                    failures += 1
            except Exception as e:
                failures += 1
                print(f"  ❌ Failed to ingest {url}: {e}")
    finally:
        try:
            client.close()
        except Exception:
            pass
        try:
            cli_credential.close()
        except Exception:
            pass

    print("\n" + "=" * 72)
    ok = len(urls) - failures
    print(f"INGESTION COMPLETE — {ok}/{len(urls)} succeeded, {failures} failed")
    print("=" * 72)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
