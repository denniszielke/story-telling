# MCP Research Server - Self-Contained Setup

## Quick Start

### 1. Activate Virtual Environment (from project root)
```bash
cd /Users/dennis/GitHub/story-telling
source .venv/bin/activate
```

### 2. Install MCP Server Dependencies
```bash
# Option A: Install core + MCP dependencies
pip install -r requirements.txt -r src/mcp_server/research_mcp_server/requirements.txt

# Option B: From this directory (if navigated here)
pip install -r requirements.txt
```

### 3. Run the MCP Server
```bash
python -m src.mcp_server.research_mcp_server.server
```

The server is hosted remotely on localhost at:
```text
http://127.0.0.1:8000/mcp
```

---

## Self-Contained MCP Server Structure

This directory contains everything needed for the research MCP server:

```
src/mcp_server/research_mcp_server/
├── __init__.py                    # Package marker
├── server.py                      # MCP server implementation (2 tools)
├── start_server.py               # Startup wrapper
├── requirements.txt              # MCP-specific dependencies
├── pyproject.toml               # MCP server package config
├── README.md                    # Integration guide
├── SETUP.md                     # Complete setup documentation
├── QUICK_REFERENCE.md           # Quick reference for commands
├── SETUP_COMPLETE.md            # Setup completion summary
└── opencode-config.example.json # Example opencode configuration
```

---

## What's in This MCP Server

### Tools Provided

1. **`search_comparable_case_studies`**
   - Searches for similar customer scenarios
   - Input: scenario_description, top_results
   - Filters on "case-study" classification

2. **`recommend_methodology`**
   - Recommends methodologies for problems
   - Input: problem_statement, top_results
   - Filters on "method" classification

### Dependencies

- `mcp>=0.1.0` - Model Context Protocol
- `azure-search-documents>=12.0.0` - Azure AI Search
- `azure-identity>=1.25.3` - Azure authentication
- `openai>=2.40.0` - Azure OpenAI embeddings
- `python-dotenv>=1.2.2` - Environment configuration

---

## Setup Options

### Option 1: From Project Root (Recommended)
```bash
cd /Users/dennis/GitHub/story-telling
source .venv/bin/activate
python -m src.mcp_server.research_mcp_server.server
```

### Option 2: Standalone from This Directory
```bash
cd src/mcp_server/research_mcp_server
source ../../../../.venv/bin/activate
python -m src.mcp_server.research_mcp_server.server
```

### Option 3: Direct Script Execution
```bash
python src/mcp_server/research_mcp_server/start_server.py
```

### Optional: Custom host/port/path
```bash
RESEARCH_MCP_HOST=127.0.0.1 RESEARCH_MCP_PORT=8010 RESEARCH_MCP_PATH=/mcp python -m src.mcp_server.research_mcp_server.server
```

---

## Environment Configuration

Ensure your `.env` file (at project root) contains:
```
AZURE_AI_SEARCH_ENDPOINT=<your-endpoint>
AZURE_AI_SEARCH_INDEX_NAME=<your-index-name>
AZURE_OPENAI_ENDPOINT=<your-openai-endpoint>
AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME=text-embedding-3-small
AZURE_OPENAI_EMBEDDING_API_VERSION=2024-10-21
AZURE_OPENAI_EMBEDDING_DIMENSIONS=1536
```

---

## Opencode Web Integration

### Configuration for Opencode

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

---

## File Reference

- **[README.md](README.md)** - Integration guide and tool descriptions
- **[server.py](server.py)** - Main MCP server implementation
- **[requirements.txt](requirements.txt)** - Python dependencies
- **[SETUP.md](SETUP.md)** - Complete setup instructions
- **[QUICK_REFERENCE.md](QUICK_REFERENCE.md)** - Quick command reference
- **[SETUP_COMPLETE.md](SETUP_COMPLETE.md)** - Setup completion guide
- **[opencode-config.example.json](opencode-config.example.json)** - Opencode configuration example

---

## Troubleshooting

### Import Errors
```bash
# Run from project root so Python can resolve the src package
cd /Users/dennis/GitHub/story-telling
python -m src.mcp_server.research_mcp_server.server
```

### Azure Authentication
```bash
# Via Azure CLI
az login

# Or set environment variables
export AZURE_IDENTITY_PROVIDER=credential
```

### MCP Connection Issues
- Verify the server starts without errors and is listening on `127.0.0.1:8000`
- Ensure opencode is configured with `"type": "remote"` and the same URL
- If you changed port/path, update both server env vars and opencode URL

---

## Development

### Install in Development Mode (from MCP server dir)
```bash
pip install -e .
```

### Run Tests
```bash
pytest
```

### Code Quality
```bash
black src/mcp_server/research_mcp_server/
ruff check src/mcp_server/research_mcp_server/
```

---

## Hosting Model

This server is now a remote MCP endpoint hosted on localhost using Streamable HTTP.

- Endpoint: `http://127.0.0.1:8000/mcp`
- Transport: `streamable-http`
- opencode connection type: `remote`
