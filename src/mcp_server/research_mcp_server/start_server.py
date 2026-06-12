#!/usr/bin/env python3
"""Simple startup script for the MCP research server.

Works after activating venv from project root.
Usage: source .venv/bin/activate && python src/mcp_server/research_mcp_server/start_server.py
"""

import sys
from pathlib import Path

# Add project root to path if needed
project_root = Path(__file__).parent.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.mcp_server.research_mcp_server.server import run

if __name__ == "__main__":
    run()
