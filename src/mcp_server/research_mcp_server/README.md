# Research Architecture MCP Server

An MCP (Model Context Protocol) server that exposes architecture research tools for searching comparable case studies and recommending methodologies.

## Quick Start

```bash
# From project root
source .venv/bin/activate
python -m src.mcp_server.research_mcp_server.server
```

Remote MCP endpoint:
`http://127.0.0.1:8000/mcp`

## Available Tools

### 1. `search_comparable_case_studies`
Search for comparable case studies based on a scenario description.

**Input:**
- `scenario_description` (required): Natural language description (e.g., "enterprise using multi-agent systems for document processing")
- `top_results` (optional): Max number of results (default: 5)

### 2. `recommend_methodology`
Recommend architectural methodologies for a given problem.

**Input:**
- `problem_statement` (required): Description of technical problem  
- `top_results` (optional): Max number of recommendations (default: 5)

## Hosting Mode

This server is configured as a remote MCP endpoint hosted on localhost using `streamable-http`.

- Host: `127.0.0.1`
- Port: `8000` (default)
- Path: `/mcp`

You can override host/port/path with environment variables:

- `RESEARCH_MCP_HOST`
- `RESEARCH_MCP_PORT`
- `RESEARCH_MCP_PATH`

A `GET /health` endpoint is exposed for readiness/liveness probes and returns
`{"status": "ok"}` when the server is up.

## Run in a Container / Azure Container Apps

A `Dockerfile` is included. The build context is the **repository root** (so the
`./src` package tree is copied into the image):

```bash
# Build (from the repo root)
docker build -f src/mcp_server/research_mcp_server/Dockerfile -t research-mcp-server .

# Run locally
docker run --rm -p 8000:8000 \
  -e AZURE_AI_SEARCH_ENDPOINT="https://<search>.search.windows.net" \
  -e AZURE_AI_SEARCH_INDEX_NAME="<index>" \
  -e AZURE_OPENAI_ENDPOINT="https://<aoai>.openai.azure.com" \
  research-mcp-server
```

Inside the container the server binds to `0.0.0.0:8000` (set via `ENV` in the
`Dockerfile`) so it can receive ingress traffic.

### Deploy to Azure Container Apps

Use the deploy script — it remote-builds the image in ACR (ACR Tasks, no local
Docker needed) and deploys/updates the Container App, then prints the `…/mcp`
URL. All settings are read from `./.env` (written by `azd up`).

```bash
# Build the image in ACR, then deploy (first deploy or after code changes)
python scripts/deploy_research_mcp_server.py --build

# Deploy only — image already in ACR, uses :latest (or the TAG env var)
python scripts/deploy_research_mcp_server.py
```

Environment variables (populated automatically from `.env` after `azd up`):

| Variable | Purpose | Default |
| --- | --- | --- |
| `AZURE_CONTAINER_REGISTRY_ENDPOINT` | ACR login server (required) | — |
| `AZURE_RESOURCE_GROUP` | Target resource group (required) | — |
| `AZURE_CONTAINER_APPS_ENVIRONMENT` | Container Apps environment (required) | — |
| `AZURE_AI_SEARCH_ENDPOINT` | Azure AI Search endpoint (required) | — |
| `AZURE_AI_SEARCH_INDEX_NAME` | Search index name (required) | — |
| `AZURE_OPENAI_ENDPOINT` | Azure OpenAI endpoint (required) | — |
| `RESEARCH_MCP_APP_NAME` | Container App name | `research-mcp-server` |
| `RESEARCH_MCP_PORT` | Container target port | `8000` |
| `RESEARCH_MCP_EXTERNAL` | Expose external ingress (`true`/`false`) | `true` |
| `TAG` | Image tag to deploy | `latest` |

The script creates the app with a **system-assigned managed identity** and grants
it the **Search Index Data Reader** and **Cognitive Services OpenAI User** roles
so the server's `DefaultAzureCredential` can reach Azure AI Search and Azure
OpenAI. The resulting MCP endpoint is
`https://research-mcp-server.<env-default-domain>/mcp`.

## Tools Available

### 1. `search_comparable_case_studies`
Search for comparable case studies based on a scenario description.

**Input:**
- `scenario_description` (required): Natural language description of the customer scenario
- `top_results` (optional): Maximum number of results (default: 5)

**Example:**
```json
{
  "scenario_description": "Enterprise using multi-agent systems for document processing in manufacturing",
  "top_results": 3
}
```

### 2. `recommend_methodology`
Recommend architectural methodologies and patterns for a given problem.

**Input:**
- `problem_statement` (required): Description of the technical problem
- `top_results` (optional): Maximum number of recommendations (default: 5)

**Example:**
```json
{
  "problem_statement": "How to orchestrate multiple AI agents for complex document processing workflows",
  "top_results": 3
}
```

## Installation & Running

```bash
cd /Users/dennis/GitHub/story-telling
source .venv/bin/activate
pip install -r requirements.txt -r src/mcp_server/research_mcp_server/requirements.txt
python -m src.mcp_server.research_mcp_server.server
```

## Environment Configuration

Ensure your `.env` file contains:
```
AZURE_AI_SEARCH_ENDPOINT=<your-search-endpoint>
AZURE_AI_SEARCH_INDEX_NAME=<your-index-name>
AZURE_OPENAI_ENDPOINT=<your-openai-endpoint>
AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME=text-embedding-3-small
AZURE_OPENAI_EMBEDDING_API_VERSION=2024-10-21
AZURE_OPENAI_EMBEDDING_DIMENSIONS=1536
```

## Opencode Web Integration

### Remote MCP Configuration
```json
{
  "mcp": {
    "research-mcp": {
      "type": "remote",
      "url": "http://127.0.0.1:8000/mcp",
      "enabled": true,
      "headers": {}
    }
  }
}
```

## Troubleshooting

**Connection refused** → Start server first and verify URL `http://127.0.0.1:8000/mcp`
**Wrong URL/path** → Match opencode URL to `RESEARCH_MCP_PORT` and `RESEARCH_MCP_PATH`
**Azure auth failing** → Check `.env` and run `az login`

See [SETUP.md](SETUP.md) for full setup and troubleshooting.

