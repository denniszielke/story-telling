"""A2A 1.0 JSON-RPC host for the researcher deep agent.

Exposes the researcher as an A2A-compliant server with:

- streaming activity (every assistant message + tool call is emitted as a
  status update on the EventQueue),
- human-in-the-loop interrupts on `search_architecture_content` — the task
  transitions to `TASK_STATE_INPUT_REQUIRED` and the next user message is
  treated as the reviewer's decision (`approve` / `reject` / edited args).

Run with:

    python -m a2a_server          # from src/agents/researcher
    # or
    uvicorn a2a_server:app --host 127.0.0.1 --port 9999
"""

from __future__ import annotations

import json
import logging
import os

import uvicorn
from a2a.helpers import (
    get_message_text,
    new_task_from_user_message,
    new_text_message,
    new_text_part,
)
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
)
from a2a.types.a2a_pb2 import TaskState
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from starlette.applications import Starlette

from agent import build_agent

logger = logging.getLogger("researcher.a2a")


# A single in-process checkpointer + agent so that interrupts can be resumed
# on subsequent requests sharing the same A2A task/context.
_CHECKPOINTER = InMemorySaver()
_AGENT = build_agent(checkpointer=_CHECKPOINTER, interrupt_on_search=True)


def _parse_decision(text: str) -> dict | None:
    """Parse a reviewer reply into a LangGraph HITL decision payload.

    Accepts:
      - `approve` / `accept` / `yes`            → accept all pending interrupts
      - `reject <reason>` / `no <reason>`       → reject with feedback
      - a raw JSON object                       → passed straight through
    """
    stripped = text.strip()
    if not stripped:
        return None
    if stripped.startswith("{"):
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            return None
    lower = stripped.lower()
    if lower in {"approve", "accept", "yes", "ok", "go"}:
        return {"decisions": [{"type": "accept"}]}
    if lower.startswith(("reject", "no ", "deny")):
        _, _, reason = stripped.partition(" ")
        return {"decisions": [{"type": "reject", "message": reason or "rejected"}]}
    return None


class ResearcherAgentExecutor(AgentExecutor):
    """Streams the deep-research agent over A2A and bridges HITL interrupts."""

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        # 1. Get-or-create the A2A task
        if context.current_task:
            task = context.current_task
        else:
            task = new_task_from_user_message(context.message)
            await event_queue.enqueue_event(task)

        updater = TaskUpdater(
            event_queue=event_queue, task_id=task.id, context_id=task.context_id
        )
        await updater.update_status(
            state=TaskState.Value("TASK_STATE_WORKING"),
            message=new_text_message("Researcher started…"),
        )

        user_text = get_message_text(context.message) or ""
        # LangGraph keys checkpoints by thread_id — bind it to the A2A context.
        thread_id = task.context_id or task.id
        config = {"configurable": {"thread_id": thread_id}}

        # 2. Decide whether this is a fresh query or a HITL resume
        decision = _parse_decision(user_text) if context.current_task else None
        if decision is not None:
            agent_input: object = Command(resume=decision)
        else:
            agent_input = {"messages": [{"role": "user", "content": user_text}]}

        final_text: str | None = None
        interrupted = False
        seen_message_ids: set[str] = set()

        try:
            async for event in _AGENT.astream(
                agent_input, config=config, stream_mode="values"
            ):
                # Stream new assistant messages and tool calls
                messages = event.get("messages", []) if isinstance(event, dict) else []
                for msg in messages:
                    mid = getattr(msg, "id", None)
                    if not isinstance(msg, AIMessage) or mid in seen_message_ids:
                        continue
                    seen_message_ids.add(mid)
                    if getattr(msg, "tool_calls", None):
                        for call in msg.tool_calls:
                            await updater.update_status(
                                state=TaskState.Value("TASK_STATE_WORKING"),
                                message=new_text_message(
                                    f"🔧 tool · {call['name']}({json.dumps(call.get('args', {}))})"
                                ),
                            )
                    if isinstance(msg.content, str) and msg.content.strip():
                        await updater.update_status(
                            state=TaskState.Value("TASK_STATE_WORKING"),
                            message=new_text_message(msg.content),
                        )
                        final_text = msg.content

                # Check for an interrupt at the end of this step
                if isinstance(event, dict) and event.get("__interrupt__"):
                    interrupted = True
                    interrupts = event["__interrupt__"]
                    pending = [getattr(i, "value", i) for i in interrupts]
                    await updater.update_status(
                        state=TaskState.Value("TASK_STATE_INPUT_REQUIRED"),
                        message=new_text_message(
                            "Approval required for tool call(s):\n"
                            f"{json.dumps(pending, default=str, indent=2)}\n\n"
                            "Reply `approve`, `reject <reason>`, or a JSON decision payload."
                        ),
                    )
                    return
        except Exception as exc:  # surface failures to the A2A client
            logger.exception("Researcher run failed")
            await updater.update_status(
                state=TaskState.Value("TASK_STATE_FAILED"),
                message=new_text_message(f"Researcher failed: {exc}"),
            )
            return

        # 3. Emit the final proposal as an artifact + complete the task
        if not interrupted:
            await updater.add_artifact(
                parts=[new_text_part(text=final_text or "(no output)", media_type="text/markdown")],
                name="architecture-proposal",
            )
            await updater.update_status(
                state=TaskState.Value("TASK_STATE_COMPLETED"),
                message=new_text_message("Proposal ready."),
            )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError("Cancel is not supported.")


# -- AgentCard & app ---------------------------------------------------------

_SKILL_RESEARCH = AgentSkill(
    id="architecture-research",
    name="Architecture Research",
    description=(
        "Produces an evidence-grounded architecture proposal "
        "(Scenario Description, Architecture Concept with ADRs, Visualization) "
        "by deep-searching a curated index of customer use cases and methodologies."
    ),
    input_modes=["text/plain"],
    output_modes=["text/markdown", "text/plain"],
    tags=["architecture", "research", "deep-agent", "azure", "hitl"],
    examples=[
        "Propose an architecture for a multi-agent field service assistant.",
        "Design a compliant data platform for a European retail bank.",
    ],
)

AGENT_CARD = AgentCard(
    name="Researcher",
    description=(
        "Deep-research agent that drafts Microsoft customer architecture proposals. "
        "Each search tool call is interrupted for human review."
    ),
    version="1.0.0",
    default_input_modes=["text/plain"],
    default_output_modes=["text/markdown", "text/plain"],
    capabilities=AgentCapabilities(streaming=True),
    supported_interfaces=[
        AgentInterface(
            protocol_binding="JSONRPC",
            url=os.getenv("A2A_PUBLIC_URL", "http://127.0.0.1:9999"),
        )
    ],
    skills=[_SKILL_RESEARCH],
)


def build_app() -> Starlette:
    """Assemble the Starlette ASGI app exposing the A2A JSON-RPC endpoints."""
    handler = DefaultRequestHandler(
        agent_executor=ResearcherAgentExecutor(),
        task_store=InMemoryTaskStore(),
        agent_card=AGENT_CARD,
    )
    routes = []
    routes.extend(create_agent_card_routes(AGENT_CARD))
    routes.extend(create_jsonrpc_routes(handler, "/"))
    return Starlette(routes=routes)


app = build_app()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(
        app,
        host=os.getenv("A2A_HOST", "127.0.0.1"),
        port=int(os.getenv("A2A_PORT", "9999")),
    )
