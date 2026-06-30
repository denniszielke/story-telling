# Story-Telling — Deployment Guide

End-to-end deployment documentation for the project: Azure infrastructure
(Bicep + `azd`), the Azure AI Search index pipeline, and the Azure AI Foundry
agent deployment scripts.

## Narrative

This repo tells one story: how **skills**, **tools**, and **runtimes** combine to
build agents that go from research to action.

It starts with knowledge. The **ingestion agent** reads source URLs, uses a
**skill** to classify each one (use case, code, or method), runs the matching
processing skill, and writes the result into Azure AI Search — populating a
grounded knowledge base.

That knowledge becomes a **tool**. The **Research MCP server** exposes the index
over MCP (comparable case-study search and methodology recommendations), and the
shared **toolbox** adds Bing grounding — both reachable by any agent.

Then agents put it to work across different **runtimes**. A lightweight
**prompt agent** (the concierge) classifies intent and routes to specialists.
**Hosted agents** run as containers in Azure AI Foundry, calling models and the
toolbox. And **Shopping Claw** runs entirely inside an Azure Container Apps
Sandbox — an OpenClaw agent that never touches your machine, exposing its canvas
and A2UI surfaces through a gateway.

The throughline: the same skills and tools are reused everywhere, while the
runtime — prompt, hosted container, or sandbox — is chosen to fit the job.

---

## Table of contents

- [Prerequisites](#prerequisites)
- [Repository layout](#repository-layout)
- [1. Infrastructure deployment](#1-infrastructure-deployment)
- [2. Search index pipeline](#2-search-index-pipeline)
- [3. Agent deployment scripts](#3-agent-deployment-scripts)
- [4. Shopping Claw (sandboxed OpenClaw agent)](#4-shopping-claw-sandboxed-openclaw-agent)
- [5. Research MCP server (Azure Container Apps)](#5-research-mcp-server-azure-container-apps)
- [6. Ingestion agent (sandboxed URL ingestion)](#6-ingestion-agent-sandboxed-url-ingestion)
- [Environment variables reference](#environment-variables-reference)
- [Teardown](#teardown)

---

## Prerequisites

| Tool | Purpose |
| --- | --- |
| [Azure Developer CLI (`azd`)](https://learn.microsoft.com/azure/developer/azure-developer-cli/install-azd) | Provisions infrastructure and orchestrates deployment |
| [Azure CLI (`az`)](https://learn.microsoft.com/cli/azure/install-azure-cli) | ACR image builds and RBAC role assignments |
| Python 3.12+ | Runs the index pipeline and agent deployment scripts |
| Azure subscription | Target for all resources |

Authenticate before deploying:

```sh
az login
azd auth login
```

Install Python dependencies (a virtual environment is recommended):

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

---

## Repository layout

| Path | Description |
| --- | --- |
| `azure.yaml` | `azd` project definition and post-deploy hooks |
| `infra/` | Bicep templates and parameters |
| `infra/main.bicep` | Subscription-scoped entry point (resource group + AI project) |
| `infra/core/` | Modular Bicep for AI, ACR, monitoring, search, storage |
| `scripts/search_index_pipeline.py` | Builds and populates the Azure AI Search index |
| `scripts/deploy_*.py` | Azure AI Foundry agent deployment scripts |
| `scripts/delete_agents.py` | Removes deployed agents |
| `data/*.json` | Sample documents ingested by the index pipeline |
| `src/agents/` | Hosted agent source (Dockerfiles, code) |
| `src/agents/narrator/` | Shopping Claw — a sandboxed OpenClaw agent (canvas + A2UI) |
| `src/agents/ingestion/` | Ingestion agent — skill-driven URL → Azure AI Search ingestion (sandboxed) |

---

## 1. Infrastructure deployment

Infrastructure is defined in Bicep and deployed through `azd`. The entry point
[`infra/main.bicep`](infra/main.bicep) is **subscription-scoped**: it creates a
resource group and provisions an Azure AI Foundry project with model
deployments, optional monitoring, Azure AI Search, storage, Bing custom
grounding, and (optionally) an Azure Container Registry for hosted agents.

### Provision and deploy

```sh
azd up
```

`azd up` will prompt for an environment name, target location, and the AI
deployments location, then provision all resources. Parameter values are mapped
from environment variables in
[`infra/main.parameters.json`](infra/main.parameters.json).

### Key parameters

| Parameter | Env var | Default | Notes |
| --- | --- | --- | --- |
| `environmentName` | `AZURE_ENV_NAME` | — | Used for naming conventions |
| `resourceGroupName` | `AZURE_RESOURCE_GROUP` | `rg-<env>` | Created if absent |
| `location` | `AZURE_LOCATION` | — | Primary region for resources |
| `aiDeploymentsLocation` | `AZURE_LOCATION` | — | Region for model deployments |
| `aiFoundryResourceName` | `AZURE_AI_ACCOUNT_NAME` | `''` | Reuse an existing AI Services account |
| `aiFoundryProjectName` | `AZURE_AI_PROJECT_NAME` | `ai-project-<env>` | AI Foundry project name |
| `enableHostedAgents` | `ENABLE_HOSTED_AGENTS` | `true` | Adds an ACR for container-based agents |
| `enableMonitoring` | `ENABLE_MONITORING` | `true` | Application Insights for the AI project |
| `searchIndexName` | — | `story-telling-index` | Index name surfaced to the pipeline |
| `embeddingDimensions` | — | `1536` | Embedding vector size |

### Model deployments

By default the project deploys two models (configurable via
`aiProjectDeploymentsJson`):

- `gpt-4.1-mini` (GlobalStandard, capacity 10)
- `text-embedding-3-small` (GlobalStandard, capacity 10)

### Outputs

After provisioning, `azd` writes outputs to `.azure/<env>/.env`. The post-deploy
hook in [`azure.yaml`](azure.yaml) copies this file to the repository root as
`.env`, which the index pipeline and agent scripts load automatically. Key
outputs include:

- `AZURE_AI_PROJECT_ENDPOINT`, `AZURE_AI_PROJECT_ID`
- `AZURE_OPENAI_ENDPOINT`, `AZURE_AI_MODEL_DEPLOYMENT_NAME`
- `AZURE_AI_SEARCH_ENDPOINT`, `AZURE_AI_SEARCH_INDEX_NAME`
- `AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME`, `AZURE_OPENAI_EMBEDDING_DIMENSIONS`
- `AZURE_CONTAINER_REGISTRY_ENDPOINT` (when hosted agents are enabled)
- `BING_CUSTOM_GROUNDING_CONNECTION_NAME`, `BING_CUSTOM_GROUNDING_CONFIG_INSTANCE_NAME`

> Make sure `.env` is present at the repository root before running the index
> pipeline or agent scripts. They call `load_dotenv()` and rely on these values.

---

## 2. Search index pipeline

[`scripts/search_index_pipeline.py`](scripts/search_index_pipeline.py) creates
(or updates) the Azure AI Search index and ingests sample documents with
generated embeddings. It reads source documents from the `data/` JSON files,
extracts content (internet, image, and repository extractors), generates
embeddings via Azure OpenAI, and uploads the documents to the index.

### Run

```sh
python scripts/search_index_pipeline.py --samples_path stories-samples.json
```

The sample data files live in `data/`:

- `data/query-samples.json` (default)
- `data/stories-samples.json`
- `data/code-samples.json`

### CLI options

| Flag | Default | Description |
| --- | --- | --- |
| `--samples_path` | `data/query-samples.json` | Path to the JSON samples file to ingest |
| `--repository_extractor_mode` | env `REPOSITORY_EXTRACTOR_MODE` or `remote` | `local` (GitHub API + in-process LLM) or `remote` (ACA sandbox + Copilot CLI) |

### Required environment variables

These are populated by the infrastructure outputs (`.env`):

- `AZURE_AI_SEARCH_ENDPOINT`
- `AZURE_AI_SEARCH_INDEX_NAME`
- `AZURE_OPENAI_ENDPOINT`
- `AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME` (default `text-embedding-3-small`)
- `AZURE_OPENAI_EMBEDDING_DIMENSIONS` (default `1536`)
- `AZURE_OPENAI_EMBEDDING_API_VERSION` (default `2024-10-21`)

Authentication uses `DefaultAzureCredential` (your `az login` session). An
optional `AZURE_OPENAI_API_KEY` can be set to use key-based auth instead.

---

## 3. Agent deployment scripts

Agents are deployed to the Azure AI Foundry project provisioned in step 1. All
scripts live in `scripts/` and load configuration from `.env` via
[`deploy_helpers.py`](scripts/deploy_helpers.py).

### Deploy everything

[`scripts/deploy_agents.py`](scripts/deploy_agents.py) is the orchestrator. It
runs all four deployment stages in order:

```sh
python scripts/deploy_agents.py
```

| Stage | Script | What it deploys |
| --- | --- | --- |
| Prompt agents | [`deploy_prompt_agents.py`](scripts/deploy_prompt_agents.py) | `bike-concierge` — a prompt agent that classifies intent and routes to specialists |
| Toolbox | [`deploy_toolbox.py`](scripts/deploy_toolbox.py) | `bikesupport-tools` — a shared Foundry toolbox exposing Bing Custom Web Search via MCP |
| Hosted agents | [`deploy_hosted_agents.py`](scripts/deploy_hosted_agents.py) | Builds container images on ACR and deploys hosted agents discovered under `src/agents/` (e.g. `support-hotline`, `repair-status`) |
| Workflow agents | [`deploy_workflow_agents.py`](scripts/deploy_workflow_agents.py) | Workflow agents defined as YAML under `src/workflows/` |

You can also run any stage independently, for example:

```sh
cd scripts
python deploy_toolbox.py        # update the shared toolbox only
python deploy_hosted_agents.py  # rebuild and redeploy hosted agents only
```

### How hosted agent deployment works

1. Discovers hosted agents under `src/agents/` (each needs a `Dockerfile`).
2. Builds a `linux/amd64` image on ACR with `az acr build`.
3. Creates a hosted agent version pointing at the new image, injecting runtime
   env vars (model deployment, project endpoint, toolbox MCP endpoint).
4. Configures the agent endpoint (Responses, A2A, Invocations) and publishes an
   agent card for A2A discovery.
5. Assigns the **Azure AI User** role to the agent's managed identity at the
   project scope so it can call models and reach the toolbox (idempotent).

### Notes & prerequisites

- The toolbox stage is skipped unless `BING_CUSTOM_GROUNDING_CONNECTION_NAME`
  is set (it is, via infrastructure outputs).
- Hosted agents require `enableHostedAgents=true` (ACR present) and a valid
  `AZURE_CONTAINER_REGISTRY_ENDPOINT`.
- Workflow deployment is a no-op if no `*.yaml` files exist under
  `src/workflows/`.
- RBAC assignment requires `AZURE_AI_PROJECT_ID` to be set.

---

## 4. Shopping Claw (sandboxed OpenClaw agent)

[`src/agents/narrator/`](src/agents/narrator/) is **Shopping Claw**, a
conversational shopping concierge built on [OpenClaw](https://docs.openclaw.ai)
that runs **only inside an Azure Container Apps Sandbox** and exposes its
**canvas + A2UI** surfaces through the OpenClaw gateway. OpenClaw is never
installed or executed on your machine — a custom bring-your-own-container image
bakes it into a sandbox disk image. The agent authenticates to Azure through a
**user-assigned managed identity** (ACR pull, sandbox group, and model access).

See [`src/agents/narrator/README.md`](src/agents/narrator/README.md) for the
full design and configuration reference.

### Step 1 — remote-build the container in ACR

Runs the Docker build in the cloud via ACR Tasks (no local Docker required):

```sh
python scripts/build_narrator_image.py
# optional: pin a tag or openclaw version
python scripts/build_narrator_image.py --tag shopping-claw:v2 --openclaw-version latest
```

### Step 2 — boot the sandbox and expose the canvas + A2UI

```sh
python src/agents/narrator/shopping_claw.py
```

The orchestrator resolves (or creates) the managed identity, converts the ACR
image into a private disk image, boots the sandbox, starts the gateway inside
it, publishes the gateway port, and prints the public canvas and A2UI URLs:

```text
Canvas : https://<host>/__openclaw__/canvas/?token=...
A2UI   : https://<host>/__openclaw__/a2ui/?token=...
```

Press Enter when prompted to delete the sandbox (and its public port).

### Required configuration

| Variable | Default | Notes |
| --- | --- | --- |
| `AZURE_CONTAINER_REGISTRY_ENDPOINT` | infra output | **Required.** ACR login server |
| `NARRATOR_IMAGE_TAG` | `shopping-claw:latest` | image:tag to build / boot |
| `RESOURCE_GROUP_NAME` | `aca-sandboxes-rg` | sandbox resource group |
| `SANDBOX_GROUP_NAME` | `shopping-claw` | sandbox group name |
| `LOCATION` | `westus3` | Azure region |
| `AZURE_MANAGED_IDENTITY_RESOURCE_ID` | — | reuse an existing identity (else one is created) |
| `AZURE_OPENAI_ENDPOINT` | — | when set, the model is reached via the managed identity (no key) |

> Requires permission to create role assignments (Owner / User Access
> Administrator) at the resource-group scope, since the orchestrator grants the
> managed identity AcrPull and the SandboxGroup Data Owner role.

---

## 5. Research MCP server (Azure Container Apps)

[`src/mcp_server/research_mcp_server/`](src/mcp_server/research_mcp_server/) is a
remote **MCP server** that exposes the architecture-research tools (comparable
case-study search and methodology recommendations) over streamable HTTP. It is
packaged as a container ([`Dockerfile`](src/mcp_server/research_mcp_server/Dockerfile))
and deployed as an Azure Container App.

[`scripts/deploy_research_mcp_server.py`](scripts/deploy_research_mcp_server.py)
remote-builds the image in ACR (ACR Tasks — no local Docker required) and
creates or updates the Container App, then prints the resulting `…/mcp` URL. All
settings are read from `.env`.

### Deploy

```sh
# Build the image in ACR, then deploy (first deploy or after code changes)
python scripts/deploy_research_mcp_server.py --build

# Deploy only — image already in ACR, uses :latest (or the TAG env var)
python scripts/deploy_research_mcp_server.py
```

The script creates the app with a **system-assigned managed identity** and grants
it the **Search Index Data Reader** and **Cognitive Services OpenAI User** roles
so the server's `DefaultAzureCredential` can reach Azure AI Search and Azure
OpenAI. The resulting MCP endpoint is
`https://research-mcp-server.<env-default-domain>/mcp` (with a `/health` probe).

### Required configuration

| Variable | Default | Notes |
| --- | --- | --- |
| `AZURE_CONTAINER_REGISTRY_ENDPOINT` | infra output | **Required.** ACR login server |
| `AZURE_RESOURCE_GROUP` | infra output | **Required.** Target resource group |
| `AZURE_CONTAINER_APPS_ENVIRONMENT` | — | **Required.** Existing Container Apps environment |
| `AZURE_AI_SEARCH_ENDPOINT` | infra output | **Required.** Azure AI Search endpoint |
| `AZURE_AI_SEARCH_INDEX_NAME` | infra output | **Required.** Search index name |
| `AZURE_OPENAI_ENDPOINT` | infra output | **Required.** Azure OpenAI endpoint |
| `AZURE_AI_SEARCH_SERVICE_NAME` | infra output | Search service (for the role assignment) |
| `RESEARCH_MCP_APP_NAME` | `research-mcp-server` | Container App name |
| `RESEARCH_MCP_PORT` | `8000` | Container target port |
| `RESEARCH_MCP_EXTERNAL` | `true` | Expose external ingress (`true`/`false`) |
| `TAG` | `latest` | Image tag to deploy |

> Requires permission to create role assignments at the search service and AI
> Services account scopes. The Container Apps environment must already exist
> (`AZURE_CONTAINER_APPS_ENVIRONMENT`).

See [`src/mcp_server/research_mcp_server/README.md`](src/mcp_server/research_mcp_server/README.md)
for the available tools and local-run instructions.

---

## 6. Ingestion agent (sandboxed URL ingestion)

[`src/agents/ingestion/`](src/agents/ingestion/) is a **skill-driven ingestion
agent** that turns source URLs into Azure AI Search documents. It reuses the
index-pipeline extractors and schema, but runs **only inside an Azure Container
Apps Sandbox** from a bring-your-own-container image. For each URL it:

1. runs the **asset-identification** skill to classify the URL's objective
   (`use case` / `code` / `method`),
2. invokes the matching **processing skill** (each objective has its own
   `SKILL.md` under [`src/agents/ingestion/skills/`](src/agents/ingestion/skills/)),
   and
3. embeds and upserts the document into Azure AI Search.

Inside the sandbox the agent authenticates with a **user-assigned managed
identity** (injected as `AZURE_CLIENT_ID`) — no secrets are baked into the
image. The same identity is reused by both scripts.

### Step 1 — build the image and provision the identity

[`scripts/build_ingestion_image.py`](scripts/build_ingestion_image.py)
remote-builds the image in ACR (ACR Tasks — no local Docker required), then
creates or reuses the managed identity and grants it everything the agent needs
at runtime: **Cognitive Services OpenAI User**, **Azure AI User**, **Search
Index Data Contributor**, **Search Service Contributor**, and **AcrPull**.

```sh
python scripts/build_ingestion_image.py
# refresh the identity / roles without rebuilding the image:
python scripts/build_ingestion_image.py --no-build
```

### Step 2 — launch a sandbox per URL

[`scripts/run_ingestion_sandbox.py`](scripts/run_ingestion_sandbox.py) converts
the image into a private disk image (pulled via the managed identity) and boots
**one sandbox per URL**. A single URL runs in one sandbox; multiple URLs each
get their own sandbox, booted sequentially from the same disk image.

```sh
# one URL → one sandbox
python scripts/run_ingestion_sandbox.py --url https://example.com/case-study

# many URLs → one sandbox per URL
python scripts/run_ingestion_sandbox.py --urls https://a.com,https://b.com
python scripts/run_ingestion_sandbox.py --urls-file data/query-samples.json

# skip identification and force an objective
python scripts/run_ingestion_sandbox.py --url https://x.com --objective "use case"
```

Each sandbox streams the agent's output back to your terminal and is deleted
once its URL is processed.

### Required configuration

| Variable | Default | Notes |
| --- | --- | --- |
| `AZURE_CONTAINER_REGISTRY_ENDPOINT` | infra output | **Required.** ACR login server |
| `AZURE_AI_PROJECT_ID` | infra output | **Required (build).** Foundry project ARM id (model + project roles, infra RG) |
| `AZURE_OPENAI_ENDPOINT` | infra output | **Required.** Foundry / Azure OpenAI endpoint |
| `AZURE_AI_SEARCH_ENDPOINT` | infra output | **Required.** Azure AI Search endpoint |
| `AZURE_AI_SEARCH_INDEX_NAME` | infra output | **Required.** Target index name |
| `AZURE_AI_SEARCH_SERVICE_NAME` | infra output | Search service (else derived from the endpoint) |
| `AZURE_RESOURCE_GROUP` | infra output | Infra RG for the Search role grant (else derived from `AZURE_AI_PROJECT_ID`) |
| `INGESTION_IMAGE_NAME` | `ingestion-agent` | Image repository |
| `INGESTION_IMAGE_TAG` | `latest` | Image tag to boot |
| `INGESTION_IDENTITY_NAME` | `ingestion-agent-identity` | UAMI to create / reuse |
| `RESOURCE_GROUP_NAME` | `aca-sandboxes-rg` | Sandbox RG (also hosts the managed identity) |
| `SANDBOX_GROUP_NAME` | `ingestion-agent` | Sandbox group name |
| `LOCATION` | `westus3` | Azure region |

> Requires permission to create role assignments (Owner / User Access
> Administrator) at the AI Services account, AI Search service, ACR, and
> resource-group scopes. The launcher also grants the signed-in user the
> **Container Apps SandboxGroup Data Owner** role.

---

## Environment variables reference

| Variable | Source | Used by |
| --- | --- | --- |
| `AZURE_AI_PROJECT_ENDPOINT` | infra output | All agent scripts |
| `AZURE_AI_PROJECT_ID` | infra output | Hosted agent RBAC |
| `AZURE_AI_MODEL_DEPLOYMENT_NAME` | infra output | Prompt/hosted agents |
| `AZURE_OPENAI_ENDPOINT` | infra output | Index pipeline, hosted agents |
| `OPENAI_API_VERSION` | infra output | Hosted agents |
| `AZURE_CONTAINER_REGISTRY_ENDPOINT` | infra output | Hosted agent image builds |
| `BING_CUSTOM_GROUNDING_CONNECTION_NAME` | infra output | Toolbox |
| `BING_CUSTOM_GROUNDING_CONFIG_INSTANCE_NAME` | infra output | Toolbox |
| `AZURE_AI_SEARCH_ENDPOINT` | infra output | Index pipeline |
| `AZURE_AI_SEARCH_INDEX_NAME` | infra output | Index pipeline |
| `AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME` | infra output | Index pipeline |
| `AZURE_OPENAI_EMBEDDING_DIMENSIONS` | infra output | Index pipeline |
| `AZURE_OPENAI_EMBEDDING_API_VERSION` | infra output | Index pipeline |
| `REPOSITORY_EXTRACTOR_MODE` | optional | Index pipeline (`local` / `remote`) |
| `AZURE_OPENAI_API_KEY` | optional | Index pipeline (key-based auth) |
| `NARRATOR_IMAGE_TAG` | optional | Shopping Claw image build / boot |
| `AZURE_MANAGED_IDENTITY_RESOURCE_ID` | optional | Shopping Claw agent identity |
| `MANAGED_IDENTITY_NAME` | optional | Shopping Claw identity to create/reuse |
| `SANDBOX_GROUP_NAME` | optional | Shopping Claw sandbox group |
| `AZURE_OPENAI_ACCOUNT_ID` | optional | Shopping Claw — grants identity OpenAI User role |
| `AZURE_CONTAINER_APPS_ENVIRONMENT` | required for MCP server | Research MCP server Container App |
| `RESEARCH_MCP_APP_NAME` | optional | Research MCP server Container App name |
| `RESEARCH_MCP_PORT` | optional | Research MCP server container port |
| `RESEARCH_MCP_EXTERNAL` | optional | Research MCP server external ingress |
| `INGESTION_IMAGE_NAME` | optional | Ingestion agent image repository |
| `INGESTION_IMAGE_TAG` | optional | Ingestion agent image tag to boot |
| `INGESTION_IDENTITY_NAME` | optional | Ingestion agent UAMI to create/reuse |
| `AZURE_RESOURCE_GROUP` | infra output | Ingestion image build (identity RG), Research MCP server |
| `AZURE_AI_SEARCH_SERVICE_NAME` | infra output | Ingestion role grants, Research MCP server |

---

## Teardown

Delete **all** deployed application resources (agents, the Research MCP Container
App, and the Shopping Claw sandbox) in one step:

```sh
python scripts/delete_all.py
# also delete the sandbox resource group:
python scripts/delete_all.py --delete-resource-group
```

Or remove individual pieces:

```sh
python scripts/delete_agents.py                 # all known agents
python scripts/delete_agents.py researcher      # specific agent(s)
python scripts/delete_research_mcp_server.py     # Research MCP Container App
python scripts/delete_sandbox.py                 # Shopping Claw sandbox + group
```

Remove all Azure infrastructure:

```sh
azd down
```
