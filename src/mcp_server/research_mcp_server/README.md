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

