"""Delete all deployed resources for this project.

Runs every teardown step in order so a single command cleans up the deployment:

  1. Foundry agents          (scripts/delete_agents.py)
  2. Research MCP Container App (scripts/delete_research_mcp_server.py)
  3. Shopping Claw sandbox    (scripts/delete_sandbox.py)

Each step is best-effort: a failure in one is reported but does not stop the
others. This does NOT run ``azd down`` — remove the base infrastructure
separately when you are done.

Usage::

    python scripts/delete_all.py
    python scripts/delete_all.py --delete-resource-group   # also delete the sandbox RG
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent))

import delete_agents  # noqa: E402
import delete_research_mcp_server  # noqa: E402
import delete_sandbox  # noqa: E402


def _run(label: str, fn) -> None:
    print(f"\n=== {label} ===")
    try:
        fn()
    except SystemExit as e:  # a step may sys.exit on a hard precondition
        print(f"  ⚠️  {label} aborted: {e}")
    except Exception as e:  # noqa: BLE001
        print(f"  ⚠️  {label} failed: {e}")


def main() -> int:
    delete_rg = "--delete-resource-group" in sys.argv[1:]

    _run("Foundry agents", lambda: delete_agents.delete(None))
    _run("Research MCP server", delete_research_mcp_server.delete)
    _run("Shopping Claw sandbox", lambda: delete_sandbox.delete(delete_rg))

    print("\n✅ Teardown complete. Run `azd down` to remove base infrastructure.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
