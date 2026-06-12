# Setup Complete: Research MCP Server ✅

## Self-Contained MCP Server Ready

All files and configuration for the Research MCP Server are now contained in:
```
src/mcp_server/research_mcp_server/
```

---

## What You Have

### MCP Server Package
- `server.py` - MCP server with 2 tools
- `start_server.py` - Startup wrapper
- `__init__.py` - Package marker
- `requirements.txt` - MCP dependencies
- `pyproject.toml` - Package configuration

### Documentation
- `README.md` - Integration and tool descriptions
- `SETUP.md` - Complete setup guide (in this folder)
- `QUICK_REFERENCE.md` - Command reference (in this folder)
- `SETUP_COMPLETE.md` - This file
- `opencode-config.example.json` - Opencode configuration example

---

## Quick Start

### 1. Activate Environment (from project root)
```bash
cd /Users/dennis/GitHub/story-telling
source .venv/bin/activate
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt -r src/mcp_server/research_mcp_server/requirements.txt
```

### 3. Run the Server
```bash
python -m src.mcp_server.research_mcp_server.server
```

Server endpoint:
```text
http://127.0.0.1:8000/mcp
```

---

## For Opencode Web

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

## MCP Server Tools

### Tool 1: Search Comparable Case Studies
Search for similar customer scenarios from the knowledge base.

**Input Parameters:**
- `scenario_description` (required) - Description of customer scenario
- `top_results` (optional) - Max results to return (default: 5)

**Returns:** Structured JSON with matching case studies

### Tool 2: Recommend Methodology
Get architectural methodology recommendations for a problem.

**Input Parameters:**
- `problem_statement` (required) - Description of technical problem
- `top_results` (optional) - Max recommendations (default: 5)

**Returns:** Structured JSON with relevant methodologies

---

## File Organization

All MCP server files are self-contained:

```
src/mcp_server/research_mcp_server/
├── Core Implementation
│   ├── __init__.py
│   ├── server.py                  ← MCP server with tools
│   └── start_server.py            ← Startup wrapper
├── Configuration
│   ├── requirements.txt           ← Dependencies
│   ├── pyproject.toml            ← Package config
│   └── opencode-config.example.json
├── Documentation
│   ├── README.md                 ← Integration guide
│   ├── SETUP.md                  ← Complete setup
│   ├── QUICK_REFERENCE.md        ← Commands
│   └── SETUP_COMPLETE.md         ← This file
```

---

## Dependencies

The MCP server requires these packages:

```
mcp>=0.1.0
azure-search-documents>=12.0.0
azure-identity>=1.25.3
openai>=2.40.0
python-dotenv>=1.2.2
```

All installed in your `.venv` when you run:
```bash
pip install -r src/mcp_server/research_mcp_server/requirements.txt
```

---

## Environment Configuration

Your `.env` file should contain (at project root):

```
AZURE_AI_SEARCH_ENDPOINT=<your-azure-search-endpoint>
AZURE_AI_SEARCH_INDEX_NAME=<your-index-name>
AZURE_OPENAI_ENDPOINT=<your-openai-endpoint>
AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME=text-embedding-3-small
AZURE_OPENAI_EMBEDDING_API_VERSION=2024-10-21
AZURE_OPENAI_EMBEDDING_DIMENSIONS=1536
```

---

## Verification

Verify everything is working:

```bash
# Activate
source .venv/bin/activate

# Check imports
python -c "from src.mcp_server.research_mcp_server.server import run, server; print('✓ OK')"

# Check dependencies
pip list | grep -E "mcp|azure|openai"
```

---

## Next Steps

1. **Start the server:**
   ```bash
   source .venv.activate
   python -m src.mcp_server.research_mcp_server.server
   ```

2. **Configure opencode web** to connect to the local MCP server

3. **Use the tools** in your opencode skills to search case studies and get methodology recommendations

---

## Architecture

```
┌─────────────────────────────────────────┐
│      Opencode Web (Local)               │
│      - Skill execution                  │
│      - MCP remote connection            │
└──────────────┬──────────────────────────┘
               │ MCP Streamable HTTP
               ↓
┌─────────────────────────────────────────┐
│   Research MCP Server (This Folder)     │
│   src/mcp_server/research_mcp_server/   │
│   - search_comparable_case_studies      │
│   - recommend_methodology               │
│   - Endpoint: /mcp on localhost         │
└──────────────┬──────────────────────────┘
               │ API Calls
               ↓
┌─────────────────────────────────────────┐
│   Azure Services                        │
│   - AI Search (vector + hybrid)         │
│   - OpenAI (embeddings)                 │
└─────────────────────────────────────────┘
```

---

## Status: ✅ Ready to Use

- ✓ All files in `src/mcp_server/research_mcp_server/`
- ✓ Self-contained package structure
- ✓ Setup documentation included
- ✓ Dependencies configured
- ✓ Opencode integration ready
- ✓ Local venv setup complete

**Everything you need for the Research MCP Server is in this folder!**
