"""Delete the Research MCP server Container App.

Removes the Container App deployed by
``scripts/deploy_research_mcp_server.py``. The ACR image, Container Apps
environment and managed-identity role assignments are left in place (they are
shared infrastructure). Idempotent — does nothing if the app is absent.

Usage::

    python scripts/delete_research_mcp_server.py

Environment variables (from ``.env``):
  AZURE_RESOURCE_GROUP    resource group holding the Container App (required)
  RESEARCH_MCP_APP_NAME   Container App name (default: research-mcp-server)
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

# Allow running directly (python scripts/delete_research_mcp_server.py)
sys.path.insert(0, str(Path(__file__).parent))

from deploy_helpers import get_env  # noqa: E402  (loads .env on import)

APP_NAME = os.getenv("RESEARCH_MCP_APP_NAME", "research-mcp-server")


def delete() -> None:
    resource_group = get_env("AZURE_RESOURCE_GROUP")

    exists = subprocess.run(
        ["az", "containerapp", "show", "-g", resource_group, "-n", APP_NAME, "-o", "none"],
        capture_output=True,
        text=True,
    ).returncode == 0

    if not exists:
        print(f"Container App '{APP_NAME}' not found in '{resource_group}' — nothing to delete.")
        return

    print(f"Deleting Container App '{APP_NAME}' from '{resource_group}'...")
    subprocess.run(
        ["az", "containerapp", "delete", "-g", resource_group, "-n", APP_NAME, "--yes"],
        check=True,
    )
    print(f"✅ Deleted Container App '{APP_NAME}'.")


if __name__ == "__main__":
    delete()
