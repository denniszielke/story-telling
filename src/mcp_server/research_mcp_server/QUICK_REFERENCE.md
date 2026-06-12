# Quick Reference: Research MCP Server

## One-Time Setup
```bash
cd /Users/dennis/GitHub/story-telling
pip install -r requirements.txt -r src/mcp_server/research_mcp_server/requirements.txt
```

## Every Time You Start

```bash
cd /Users/dennis/GitHub/story-telling
source .venv/bin/activate
```

## Running the MCP Server

```bash
# Standard method (from project root) - remote MCP hosted on localhost
python -m src.mcp_server.research_mcp_server.server

# Or via wrapper script
python src/mcp_server/research_mcp_server/start_server.py
```

Endpoint:
```text
http://127.0.0.1:8000/mcp
```

## Testing Imports
```bash
python -c "from src.mcp_server.research_mcp_server.server import run, server; print('✓ OK')"
```

## Tools Available

| Tool | Purpose | Input |
|------|---------|-------|
| `search_comparable_case_studies` | Find similar scenarios | scenario_description, top_results |
| `recommend_methodology` | Get methodology recommendations | problem_statement, top_results |

## Configuring Opencode Web

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

| Problem | Solution |
|---------|----------|
| Import error | Start from project root: `/Users/dennis/GitHub/story-telling` |
| Connection error | Confirm server is running and opencode URL is `http://127.0.0.1:8000/mcp` |
| Azure auth fails | Ensure `.env` has credentials or run `az login` |

## Directory Structure (Self-Contained)

```
src/mcp_server/research_mcp_server/
├── server.py              # Main MCP server
├── start_server.py        # Startup wrapper
├── requirements.txt       # Dependencies
├── pyproject.toml        # Package config
├── README.md             # Integration guide
├── SETUP.md              # Setup instructions
├── QUICK_REFERENCE.md    # This file
├── SETUP_COMPLETE.md     # Completion guide
└── opencode-config.example.json
```

## Common Commands

```bash
# Activate venv
source .venv/bin/activate

# Check setup
python -c "from src.mcp_server.research_mcp_server.server import run; print('✓')"

# Run server
python -m src.mcp_server.research_mcp_server.server

# View dependencies
pip list | grep -E "mcp|azure|openai"

# Update dependencies
pip install --upgrade -r src/mcp_server/research_mcp_server/requirements.txt
```

## Key Files

- **Server**: `server.py` - MCP server with 2 tools
- **Setup**: `SETUP.md` - Complete documentation
- **Config**: `pyproject.toml` - Package configuration
- **Deps**: `requirements.txt` - Python dependencies
