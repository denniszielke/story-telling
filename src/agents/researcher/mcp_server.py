"""MCP server exposing the researcher deep agent.

Wraps the same `build_agent()` factory used by the A2A server, so all
business logic (tools, skills, memory, prompts) stays in `agent.py`. This
module is a pure protocol bridge: it accepts MCP tool calls and streams the
agent's activity back as MCP progress/log notifications.

Transports:
  - `stdio` (default) — for IDE/CLI MCP clients.
  - `streamable-http` — set `MCP_TRANSPORT=http` to serve on
    `http://$MCP_HOST:$MCP_PORT/mcp` (defaults 127.0.0.1:8765).

Run:
    python mcp_server.py                       # stdio
    MCP_TRANSPORT=http python mcp_server.py    # streamable HTTP
"""

from __future__ import annotations

import json
import logging
import os
import uuid

from langchain_core.messages import AIMessage
from mcp.server.fastmcp import Context, FastMCP

from agent import build_agent

logger = logging.getLogger("researcher.mcp")

# Single shared agent instance — interrupt-on-search is disabled here because
# MCP clients don't have a standard human-approval handshake. Use the A2A
# server when HITL is required.
_AGENT = build_agent(interrupt_on_search=False)


mcp = FastMCP(
    name="Researcher",
    instructions=(
        "Architecture researcher deep agent. Call `research_architecture` "
        "with a scenario description to receive an evidence-grounded "
        "proposal (Scenario, Architecture Concept with ADRs, Visualization). "
        "Use `list_skills` to inspect the agent's loaded skills."
    ),
)


@mcp.tool(
    name="research_architecture",
    description=(
        "Generate an evidence-grounded Microsoft customer architecture proposal "
        "for the given scenario. Streams activity (tool calls, intermediate "
        "messages) and returns the final markdown proposal."
    ),
)
async def research_architecture(scenario: str, ctx: Context) -> str:
    """Run the researcher agent end-to-end and stream activity to the MCP client."""
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    final_text: str | None = None
    seen_message_ids: set[str] = set()

    await ctx.info(f"Starting research (thread={thread_id})")

    async for event in _AGENT.astream(
        {"messages": [{"role": "user", "content": scenario}]},
        config=config,
        stream_mode="values",
    ):
        if not isinstance(event, dict):
            continue
        for msg in event.get("messages", []):
            mid = getattr(msg, "id", None)
            if not isinstance(msg, AIMessage) or mid in seen_message_ids:
                continue
            seen_message_ids.add(mid)
            if getattr(msg, "tool_calls", None):
                for call in msg.tool_calls:
                    await ctx.info(
                        f"tool · {call['name']}({json.dumps(call.get('args', {}))})"
                    )
            if isinstance(msg.content, str) and msg.content.strip():
                await ctx.info(msg.content[:500])
                final_text = msg.content

    return final_text or "(no output)"


@mcp.tool(
    name="list_skills",
    description="List the deep-research skills currently loaded by the agent.",
)
def list_skills() -> str:
    """Return the names and descriptions of the agent's skills."""
    from pathlib import Path

    skills_dir = Path(__file__).resolve().parent / "skills"
    entries = []
    for skill_md in sorted(skills_dir.glob("*/SKILL.md")):
        text = skill_md.read_text(encoding="utf-8")
        name = skill_md.parent.name
        desc = ""
        if text.startswith("---"):
            front = text.split("---", 2)[1]
            for line in front.splitlines():
                if line.startswith("description:"):
                    desc = line.split(":", 1)[1].strip()
                    break
        entries.append(f"- **{name}** — {desc}")
    return "\n".join(entries) or "(no skills found)"


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    transport = os.getenv("MCP_TRANSPORT", "stdio").lower()
    if transport in {"http", "streamable-http", "streamable_http", "sse"}:
        import uvicorn
        from starlette.middleware.cors import CORSMiddleware

        host = os.getenv("MCP_HOST", "127.0.0.1")
        port = int(os.getenv("MCP_PORT", "8765"))

        app = mcp.sse_app() if transport == "sse" else mcp.streamable_http_app()

        # MCP Inspector (and any browser client) sends CORS preflight `OPTIONS`
        # requests and reads the `mcp-session-id` response header. Both must be
        # whitelisted explicitly.
        app = CORSMiddleware(
            app,
            allow_origins=os.getenv("MCP_CORS_ORIGINS", "*").split(","),
            allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
            allow_headers=["*"],
            expose_headers=["mcp-session-id", "mcp-protocol-version"],
            allow_credentials=False,
        )

        uvicorn.run(app, host=host, port=port)
    else:
        mcp.run(transport="stdio")
