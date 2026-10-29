"""LangGraph incident state machine with durable checkpoints and the HITL gate."""

import asyncio
import json
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, cast

from langchain_core.messages import AIMessage, AnyMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.agent.nodes import (
    READ_ONLY_TOOLS,
    agent_reasoning_node,
    force_terminate_node,
    read_tools_node,
    remediation_node,
)
from src.agent.state import IncidentState, PendingRemediation
from src.common.config import get_settings

IncidentGraph = CompiledStateGraph[IncidentState, Any, IncidentState, IncidentState]


def route_after_reasoning(state: IncidentState) -> str:
    """Choose the next node from the latest reasoning turn."""
    settings = get_settings()
    if (
        state.get("step_count", 0) >= settings.MAX_AGENT_STEPS
        or state.get("tokens_used", 0) >= settings.MAX_AGENT_TOKENS
    ):
        return "force_terminate"

    messages = state["messages"]
    last_message = messages[-1] if messages else None
    if not isinstance(last_message, AIMessage) or not last_message.tool_calls:
        return END

    tool_names = {call["name"] for call in last_message.tool_calls}
    if tool_names & READ_ONLY_TOOLS:
        return "read_tools_node"
    if "execute_remediation" in tool_names:
        return "remediation_node"
    return END


def route_after_read_tools(state: IncidentState) -> str:
    """Route to remediation_node if a pending remediation was queued alongside read tools."""
    if state.get("pending_remediation") is not None:
        return "remediation_node"
    return "agent_reasoning"


def build_incident_graph(
    checkpointer: BaseCheckpointSaver[Any] | None = None,
) -> IncidentGraph:
    """Build and compile the incident graph with the mandatory remediation interrupt."""
    builder = StateGraph(IncidentState)
    builder.add_node("agent_reasoning", agent_reasoning_node)
    builder.add_node("read_tools_node", read_tools_node)
    builder.add_node("remediation_node", remediation_node)
    builder.add_node("force_terminate", force_terminate_node)

    builder.add_edge(START, "agent_reasoning")
    builder.add_conditional_edges(
        "agent_reasoning",
        route_after_reasoning,
        {
            "read_tools_node": "read_tools_node",
            "remediation_node": "remediation_node",
            "force_terminate": "force_terminate",
            END: END,
        },
    )
    builder.add_conditional_edges(
        "read_tools_node",
        route_after_read_tools,
        {
            "remediation_node": "remediation_node",
            "agent_reasoning": "agent_reasoning",
        },
    )
    builder.add_edge("remediation_node", "agent_reasoning")
    builder.add_edge("force_terminate", END)

    return builder.compile(
        checkpointer=checkpointer,
        interrupt_before=["remediation_node"],
    )


_checkpoint_setup_done: bool = False


@asynccontextmanager
async def postgres_graph() -> AsyncIterator[IncidentGraph]:
    """Open a PostgreSQL checkpoint store and yield the compiled incident graph."""
    global _checkpoint_setup_done
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    settings = get_settings()
    async with AsyncPostgresSaver.from_conn_string(settings.SYNC_DATABASE_URL) as checkpointer:
        if not _checkpoint_setup_done:
            await checkpointer.setup()
            _checkpoint_setup_done = True
        yield build_incident_graph(checkpointer)


def _find_tool_result(
    messages: list[AnyMessage],
    tool_call_id: str,
) -> dict[str, Any] | None:
    """Return the JSON payload of the ToolMessage paired with a write call."""
    for message in reversed(messages):
        if not isinstance(message, ToolMessage) or message.tool_call_id != tool_call_id:
            continue
        if not isinstance(message.content, str):
            return None
        try:
            parsed = json.loads(message.content)
        except (json.JSONDecodeError, TypeError):
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


async def resume_with_approval(
    thread_id: str,
    decision: str,
    operator_id: str,
    comment: str = "",
) -> dict[str, Any]:
    """Resume an interrupted incident after an explicit approval or rejection."""
    normalized_decision = decision.strip().upper()
    if normalized_decision not in {"APPROVE", "REJECT"}:
        return {
            "status": "error",
            "error_code": "INVALID_DECISION",
            "message": f"Unsupported decision '{decision}'. Use APPROVE or REJECT.",
            "valid_decisions": ["APPROVE", "REJECT"],
        }
    if not operator_id.strip():
        return {
            "status": "error",
            "error_code": "INVALID_OPERATOR",
            "message": "operator_id is required for the remediation audit trail.",
        }

    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
    async with postgres_graph() as graph:
        snapshot = await graph.aget_state(config)
        pending = cast(PendingRemediation | None, snapshot.values.get("pending_remediation"))
        if pending is None or "remediation_node" not in snapshot.next:
            return {
                "status": "error",
                "error_code": "NO_PENDING_REMEDIATION",
                "message": f"Thread '{thread_id}' has no remediation awaiting approval.",
                "thread_id": thread_id,
            }

        approval_status = "APPROVED" if normalized_decision == "APPROVE" else "REJECTED"
        await graph.aupdate_state(
            config,
            {
                "approval_status": approval_status,
                "approved_by": operator_id,
                "approval_comment": comment,
            },
        )
        final_state = await graph.ainvoke(None, config)

    messages: list[AnyMessage] = (
        final_state.get("messages", []) if isinstance(final_state, dict) else []
    )
    result = _find_tool_result(messages, pending["tool_call_id"])
    assistant_message = next(
        (
            message.content
            for message in reversed(messages)
            if isinstance(message, AIMessage) and isinstance(message.content, str)
        ),
        "",
    )
    if result is None:
        return {
            "status": "error",
            "error_code": "REMEDIATION_RESULT_MISSING",
            "message": f"Thread '{thread_id}' resumed without a recorded remediation result.",
            "thread_id": thread_id,
            "approval_status": approval_status,
        }

    return {
        "status": "success",
        "thread_id": thread_id,
        "decision": normalized_decision,
        "approval_status": approval_status,
        "result": result,
        "assistant_message": assistant_message,
    }
