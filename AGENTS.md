# AGENTS.md

Operational guide for deploying and tearing down this project. It is the
task-oriented companion to [`README.md`](README.md) (which has the full
reference). Use this file when you need the exact command for a given job.

All scripts load configuration from `.env` at the repository root (written by
`azd up` and copied by the post-deploy hook in [`azure.yaml`](azure.yaml)).
Authenticate first with `az login` and `azd auth login`, and install
dependencies with `pip install -r requirements.txt`.

---

## Deployment tasks

| Task | Command | Notes |
| --- | --- | --- |
| Provision infrastructure | `azd up` | Resource group, AI Foundry project, models, Search, storage, ACR |
| Build & populate search index | `python scripts/search_index_pipeline.py --samples_path stories-samples.json` | Reads `data/*.json`, embeds, uploads |
| Deploy all Foundry agents | `python scripts/deploy_agents.py` | Orchestrates prompt + toolbox + hosted + workflow stages |
| Deploy prompt agents only | `python scripts/deploy_prompt_agents.py` | `researcher-concierge` |
| Deploy toolbox only | `python scripts/deploy_toolbox.py` | Shared Bing/Search MCP toolbox |
| Deploy hosted agents only | `python scripts/deploy_hosted_agents.py` | Builds images on ACR, deploys agents under `src/agents/` |
| Deploy workflow agents only | `python scripts/deploy_workflow_agents.py` | No-op if no `src/workflows/*.yaml` |
| Build Shopping Claw image | `python scripts/build_narrator_image.py` | Remote ACR build (no local Docker) |
| Run Shopping Claw sandbox | `python src/agents/narrator/shopping_claw.py` | Boots sandbox, prints canvas + A2UI URLs |
| Build ingestion image + identity | `python scripts/build_ingestion_image.py` | Remote ACR build + UAMI + role grants |
| Refresh ingestion identity only | `python scripts/build_ingestion_image.py --no-build` | Re-grants roles without rebuilding |
| Ingest a single URL | `python scripts/run_ingestion_sandbox.py --url <url>` | One sandbox; classify + process + index |
| Ingest multiple URLs | `python scripts/run_ingestion_sandbox.py --urls <a,b>` | One sandbox **per URL** (sequential) |
| Ingest URLs from a file | `python scripts/run_ingestion_sandbox.py --urls-file <json>` | One sandbox per URL from JSON list |
| Deploy Research MCP server | `python scripts/deploy_research_mcp_server.py --build` | Builds image in ACR, deploys Container App |
| Redeploy Research MCP (no build) | `python scripts/deploy_research_mcp_server.py` | Uses `:latest` (or `TAG`) |

### Prerequisites per task

- **Hosted agents** require `enableHostedAgents=true` (ACR present) and a valid
  `AZURE_CONTAINER_REGISTRY_ENDPOINT`. RBAC needs `AZURE_AI_PROJECT_ID`.
- **Toolbox** is skipped unless `BING_CUSTOM_GROUNDING_CONNECTION_NAME` is set.
- **Research MCP server** requires an existing Container Apps environment in
  `AZURE_CONTAINER_APPS_ENVIRONMENT`, plus `AZURE_RESOURCE_GROUP`,
  `AZURE_CONTAINER_REGISTRY_ENDPOINT`, `AZURE_AI_SEARCH_ENDPOINT`,
  `AZURE_AI_SEARCH_INDEX_NAME` and `AZURE_OPENAI_ENDPOINT`. The script assigns
  the app's managed identity **Search Index Data Reader** and **Cognitive
  Services OpenAI User**.
- **Ingestion agent (build)** requires `AZURE_CONTAINER_REGISTRY_ENDPOINT`,
  `AZURE_AI_PROJECT_ID`, `AZURE_AI_SEARCH_ENDPOINT`. It creates/reuses a UAMI
  (`INGESTION_IDENTITY_NAME`) in the sandbox RG (`RESOURCE_GROUP_NAME`, default
  `aca-sandboxes-rg`) and grants it **Cognitive Services OpenAI User**, **Azure
  AI User**, **Search Index Data Contributor**, **Search Service Contributor**,
  and **AcrPull**. The Search role uses the infra RG derived from
  `AZURE_AI_PROJECT_ID` (or `AZURE_RESOURCE_GROUP` if set).
- **Ingestion agent (launch)** reuses that UAMI and requires
  `AZURE_OPENAI_ENDPOINT`, `AZURE_AI_SEARCH_ENDPOINT`,
  `AZURE_AI_SEARCH_INDEX_NAME`. It needs permission to create role assignments
  at the resource-group scope (grants the signed-in user SandboxGroup Data Owner
  and the UAMI AcrPull). Single URL → one sandbox; multiple URLs → one per URL.
- **Shopping Claw** requires permission to create role assignments at the
  resource-group scope (it grants the managed identity AcrPull and the
  SandboxGroup Data Owner role).

---

## Teardown tasks

| Task | Command | Removes |
| --- | --- | --- |
| Delete everything | `python scripts/delete_all.py` | Agents + Research MCP app + sandbox (best-effort) |
| Delete everything incl. sandbox RG | `python scripts/delete_all.py --delete-resource-group` | Above + the sandbox resource group |
| Delete Foundry agents | `python scripts/delete_agents.py` | All known agents |
| Delete specific agent(s) | `python scripts/delete_agents.py researcher` | Named agent(s) only |
| Delete Research MCP server | `python scripts/delete_research_mcp_server.py` | The Container App (keeps env/ACR/roles) |
| Delete Shopping Claw sandbox | `python scripts/delete_sandbox.py` | Sandboxes, disk images, sandbox group |
| Delete sandbox + its RG | `python scripts/delete_sandbox.py --delete-resource-group` | Above + sandbox resource group |
| Delete ingestion sandbox group | `SANDBOX_GROUP_NAME=ingestion-agent python scripts/delete_sandbox.py` | Leftover ingestion group/disk images (sandboxes auto-delete per URL) |
| Remove base infrastructure | `azd down` | All `azd`-provisioned resources |

> `delete_all.py` does **not** run `azd down`. Remove the base infrastructure
> separately once the application resources are gone.

---

## Key environment variables

See the [Environment variables reference](README.md#environment-variables-reference)
in the README for the complete table. The most load-bearing ones:

| Variable | Used by |
| --- | --- |
| `AZURE_RESOURCE_GROUP` | Research MCP deploy/delete |
| `AZURE_CONTAINER_APPS_ENVIRONMENT` | Research MCP deploy |
| `AZURE_CONTAINER_REGISTRY_ENDPOINT` | Image builds (hosted agents, MCP, Shopping Claw) |
| `AZURE_AI_PROJECT_ENDPOINT` / `AZURE_AI_PROJECT_ID` | Foundry agent deploy + RBAC |
| `AZURE_AI_SEARCH_ENDPOINT` / `AZURE_AI_SEARCH_INDEX_NAME` | Index pipeline, Research MCP |
| `AZURE_OPENAI_ENDPOINT` | Index pipeline, agents, Research MCP |
| `INGESTION_IDENTITY_NAME` / `INGESTION_IMAGE_NAME` / `INGESTION_IMAGE_TAG` | Ingestion build/launch |
| `RESOURCE_GROUP_NAME` / `SANDBOX_GROUP_NAME` | Shopping Claw + ingestion sandbox deploy/delete |
| `RESEARCH_MCP_APP_NAME` / `RESEARCH_MCP_PORT` / `RESEARCH_MCP_EXTERNAL` | Research MCP Container App |
