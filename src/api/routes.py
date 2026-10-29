"""FastAPI REST and SSE endpoints for the OmniOps incident agent."""

import json
from collections.abc import AsyncIterator
from typing import Any, cast

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig

from src.agent.graph import postgres_graph, resume_with_approval
from src.agent.state import IncidentState
from src.api.schemas import ApprovalRequest, IncidentStreamRequest
from src.common.config import get_settings
from src.common.logger import setup_logger
from src.db.seed import reset_database

logger = setup_logger("api_routes")


async def verify_api_key(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> None:
    """Enforce API key authentication in production or when an X-API-Key header is sent."""
    settings = get_settings()
    if settings.ENV == "production" or x_api_key is not None:
        if x_api_key != settings.API_KEY:
            raise HTTPException(
                status_code=401,
                detail={
                    "status": "error",
                    "error_code": "UNAUTHORIZED",
                    "message": "Invalid or missing X-API-Key header.",
                },
            )


router = APIRouter(dependencies=[Depends(verify_api_key)])


def _sse(event: str, data: dict[str, Any]) -> str:
    """Encode one Server-Sent Event frame."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def _decode_tool_content(content: Any) -> Any:
    """Return a tool payload as JSON when possible, falling back to the raw value."""
    if not isinstance(content, str):
        return content
    try:
        return json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return content


def _message_events(message: AnyMessage) -> list[str]:
    """Translate one graph message into the documented SSE events."""
    if isinstance(message, AIMessage):
        frames: list[str] = []
        if isinstance(message.content, str) and message.content.strip():
            frames.append(_sse("token", {"content": message.content}))
        frames.extend(
            _sse(
                "tool_call",
                {"tool_call_id": call["id"], "name": call["name"], "arguments": call["args"]},
            )
            for call in message.tool_calls
        )
        return frames
    if isinstance(message, ToolMessage):
        return [
            _sse(
                "tool_result",
                {
                    "tool_call_id": message.tool_call_id,
                    "name": message.name,
                    "result": _decode_tool_content(message.content),
                },
            )
        ]
    return []


def _approval_frame(thread_id: str, pending: Any) -> str:
    """Announce a remediation waiting at the human approval gate."""
    return _sse(
        "approval_required",
        {
            "thread_id": thread_id,
            "pending_remediation": pending,
            "message": "Remediation requires an explicit operator decision.",
        },
    )


def _done_frame(thread_id: str, status: str, state: dict[str, Any]) -> str:
    """Close the stream with the terminal status and budget usage."""
    return _sse(
        "done",
        {
            "thread_id": thread_id,
            "status": status,
            "step_count": state.get("step_count", 0),
            "tokens_used": state.get("tokens_used", 0),
            "fallback_used": bool(state.get("fallback_used", False)),
        },
    )


async def _incident_stream(payload: IncidentStreamRequest) -> AsyncIterator[str]:
    """Run the incident graph and stream its progress as SSE frames."""
    config: RunnableConfig = {"configurable": {"thread_id": payload.thread_id}}
    try:
        async with postgres_graph() as graph:
            snapshot = await graph.aget_state(config)

            if snapshot.next:
                pending = snapshot.values.get("pending_remediation")
                if pending is not None:
                    yield _approval_frame(payload.thread_id, pending)
                    yield _done_frame(payload.thread_id, "AWAITING_APPROVAL", snapshot.values)
                else:
                    yield _done_frame(payload.thread_id, "INTERRUPTED", snapshot.values)
                return

            # Partial input is merged into the checkpointed channels; absent keys keep
            # their persisted values, which is why the TypedDict is cast here.
            new_turn = cast(
                IncidentState,
                {"messages": [HumanMessage(content=payload.query)]},
            )
            async for chunk in graph.astream(new_turn, config, stream_mode="updates"):
                for node_update in chunk.values():
                    # ``__interrupt__`` frames carry interrupt objects, not state updates.
                    if not isinstance(node_update, dict):
                        continue
                    for message in node_update.get("messages", []):
                        for frame in _message_events(message):
                            yield frame

            snapshot = await graph.aget_state(config)

        pending = snapshot.values.get("pending_remediation")
        if "remediation_node" in snapshot.next and pending is not None:
            yield _approval_frame(payload.thread_id, pending)
            yield _done_frame(payload.thread_id, "AWAITING_APPROVAL", snapshot.values)
        else:
            yield _done_frame(payload.thread_id, "COMPLETED", snapshot.values)
    except Exception:
        logger.exception("Incident stream failed for thread %s", payload.thread_id)
        yield _sse(
            "done",
            {
                "thread_id": payload.thread_id,
                "status": "FAILED",
                "error_code": "AGENT_EXECUTION_ERROR",
            },
        )


@router.post("/incident/stream")
async def stream_incident(payload: IncidentStreamRequest) -> StreamingResponse:
    """Start or continue an incident investigation and stream its events."""
    return StreamingResponse(
        _incident_stream(payload),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/incident/approve")
async def approve_incident(payload: ApprovalRequest) -> dict[str, Any]:
    """Resume a paused incident after an explicit operator decision."""
    outcome = await resume_with_approval(
        payload.thread_id,
        payload.decision,
        payload.operator_id,
        payload.comment,
    )
    if outcome.get("status") == "error":
        status_code = 404 if outcome.get("error_code") == "NO_PENDING_REMEDIATION" else 400
        raise HTTPException(status_code=status_code, detail=outcome)
    return outcome


@router.post("/infra/reset")
async def reset_infra() -> dict[str, Any]:
    """Reset operational tables back to the initial seeded incident state."""
    await reset_database()
    return {"status": "success", "message": "Operational tables reset to initial seed state."}
