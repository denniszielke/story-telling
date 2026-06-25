# Story-Telling — Deployment Guide

End-to-end deployment documentation for the project: Azure infrastructure
(Bicep + `azd`), the Azure AI Search index pipeline, and the Azure AI Foundry
agent deployment scripts.

---

## Table of contents

- [Prerequisites](#prerequisites)
- [Repository layout](#repository-layout)
- [1. Infrastructure deployment](#1-infrastructure-deployment)
- [2. Search index pipeline](#2-search-index-pipeline)
- [3. Agent deployment scripts](#3-agent-deployment-scripts)
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

---

## Teardown

Remove deployed agents:

```sh
cd scripts
python delete_agents.py                 # delete all known agents
python delete_agents.py support-hotline # delete specific agent(s)
```

Remove all Azure infrastructure:

```sh
azd down
```
