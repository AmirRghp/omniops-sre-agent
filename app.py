"""Chainlit Interactive SRE Console for OmniOps incident investigation and HITL remediation."""

import json
import time
import uuid
from typing import Any, Literal, cast

import chainlit as cl
from chainlit.config import config as cl_config
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig

from src.agent.graph import postgres_graph, resume_with_approval
from src.agent.state import IncidentState
from src.agent.ui_helpers import (
    format_approval_card,
    format_remediation_summary,
    format_step_header,
    format_welcome_message,
)
from src.common.logger import setup_logger
from src.db.session import init_db

logger = setup_logger("chainlit_app")

cl_config.ui.name = "OmniOps SRE Agent"
cl_config.ui.default_theme = "dark"
cl_config.ui.custom_css = "/public/custom.css"
cl_config.ui.cot = "full"


async def _send_approval_card(thread_id: str, pending: dict[str, Any]) -> None:
    """Render the interactive HITL approval card and action buttons."""
    card_md = format_approval_card(pending)
    actions = [
        cl.Action(
            name="approve_action",
            label="✅ تایید و اجرا (Approve)",
            payload={
                "thread_id": thread_id,
                "decision": "APPROVE",
                "service_name": pending["service_name"],
                "action_type": pending["action_type"],
                "parameters": pending["parameters"],
            },
        ),
        cl.Action(
            name="reject_action",
            label="❌ لغو عملیات (Reject)",
            payload={
                "thread_id": thread_id,
                "decision": "REJECT",
                "service_name": pending["service_name"],
                "action_type": pending["action_type"],
            },
        ),
    ]
    await cl.Message(content=card_md, actions=actions).send()  # type: ignore[no-untyped-call]


@cl.on_chat_start
async def on_chat_start() -> None:
    """Initialize the operational session and database connection."""
    await init_db()
    thread_id = f"inc_{uuid.uuid4().hex[:10]}"
    cl.user_session.set("thread_id", thread_id)  # type: ignore[no-untyped-call]
    await cl.Message(content=format_welcome_message()).send()  # type: ignore[no-untyped-call]


@cl.on_message
async def on_message(message: cl.Message) -> None:
    """Process an SRE query, stream tool execution steps, and gate remediations."""
    thread_id = cast(str | None, cl.user_session.get("thread_id"))  # type: ignore[no-untyped-call]
    if not thread_id:
        thread_id = f"inc_{uuid.uuid4().hex[:10]}"
        cl.user_session.set("thread_id", thread_id)  # type: ignore[no-untyped-call]

    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
    new_turn = cast(IncidentState, {"messages": [HumanMessage(content=message.content)]})

    tracked_calls: dict[str, dict[str, Any]] = {}
    final_content: str = ""

    try:
        async with postgres_graph() as graph:
            existing_snapshot = await graph.aget_state(config)
            existing_pending = existing_snapshot.values.get("pending_remediation")
            if "remediation_node" in existing_snapshot.next and existing_pending is not None:
                await _send_approval_card(thread_id, existing_pending)
                return

            async for chunk in graph.astream(new_turn, config, stream_mode="updates"):
                for node_name, update in chunk.items():
                    if not isinstance(update, dict):
                        continue

                    if node_name == "agent_reasoning":
                        for msg in update.get("messages", []):
                            if isinstance(msg, AIMessage):
                                if isinstance(msg.content, str):
                                    final_content = msg.content
                                for call in msg.tool_calls:
                                    call_id = call.get("id") or str(uuid.uuid4())
                                    tracked_calls[call_id] = {
                                        "name": call.get("name", "tool"),
                                        "args": call.get("args", {}),
                                        "start_time": time.perf_counter(),
                                    }

                    elif node_name == "read_tools_node":
                        for msg in update.get("messages", []):
                            if isinstance(msg, ToolMessage):
                                call_id = msg.tool_call_id
                                call_info = tracked_calls.get(call_id, {})
                                tool_name = msg.name or str(call_info.get("name", "tool"))
                                args = call_info.get("args", {})
                                start_time = call_info.get("start_time", time.perf_counter())
                                duration_ms = (time.perf_counter() - start_time) * 1000

                                try:
                                    result = (
                                        json.loads(msg.content)
                                        if isinstance(msg.content, str)
                                        else msg.content
                                    )
                                except Exception:
                                    result = msg.content

                                source_mode = (
                                    result.get("source_mode") if isinstance(result, dict) else None
                                )
                                is_error = (
                                    isinstance(result, dict) and result.get("status") == "error"
                                )

                                step_title = format_step_header(
                                    tool_name=tool_name,
                                    duration_ms=duration_ms,
                                    source_mode=source_mode,
                                    is_error=is_error,
                                )

                                step = cl.Step(name=step_title, type="tool")
                                step.input = json.dumps(args, indent=2, ensure_ascii=False)
                                step.output = json.dumps(result, indent=2, ensure_ascii=False)
                                await step.send()  # type: ignore[no-untyped-call]

                    elif node_name == "force_terminate":
                        for msg in update.get("messages", []):
                            if isinstance(msg, AIMessage) and isinstance(msg.content, str):
                                final_content = msg.content

            snapshot = await graph.aget_state(config)

        pending = snapshot.values.get("pending_remediation")
        if "remediation_node" in snapshot.next and pending is not None:
            await _send_approval_card(thread_id, pending)
        elif final_content:
            await cl.Message(content=final_content).send()  # type: ignore[no-untyped-call]

    except Exception as exc:
        logger.exception("Incident investigation failed: %s", exc)
        await cl.Message(  # type: ignore[no-untyped-call]
            content="⚠️ **خطا در پردازش حادثه:**\n\n"
            "ارتباط با سرویس استنتاج مدل یا پایگاه داده با اشکال مواجه شد. "
            "لطفاً وضعیت سرویس‌ها را بررسی کرده و مجدداً تلاش فرمایید."
        ).send()


async def _handle_operator_decision(
    action: cl.Action,
    decision: Literal["APPROVE", "REJECT"],
) -> None:
    """Shared handler for operator approval or rejection callbacks."""
    payload = action.payload or {}
    session_tid = cl.user_session.get("thread_id")  # type: ignore[no-untyped-call]
    thread_id = str(payload.get("thread_id") or session_tid or "")
    service_name = str(payload.get("service_name", "service"))
    action_type = str(payload.get("action_type", "remediation"))
    parameters = payload.get("parameters", {})

    await action.remove()  # type: ignore[no-untyped-call]

    comment = (
        "Approved via Chainlit SRE Console"
        if decision == "APPROVE"
        else "Rejected via Chainlit SRE Console"
    )
    start_time = time.perf_counter()
    outcome = await resume_with_approval(
        thread_id=thread_id,
        decision=decision,
        operator_id="sre_console_operator",
        comment=comment,
    )
    duration_ms = (time.perf_counter() - start_time) * 1000

    result = outcome.get("result", {})
    step_title = format_step_header(
        tool_name="execute_remediation",
        duration_ms=duration_ms,
        source_mode=None,
        is_error=decision == "APPROVE" and outcome.get("status") == "error",
    )
    step = cl.Step(name=step_title, type="tool")
    step_input: dict[str, Any] = {
        "service_name": service_name,
        "action_type": action_type,
    }
    if decision == "APPROVE":
        step_input["parameters"] = parameters
    else:
        step_input["status"] = "ABORTED_BY_OPERATOR"

    step.input = json.dumps(step_input, indent=2, ensure_ascii=False)
    step.output = json.dumps(result, indent=2, ensure_ascii=False)
    await step.send()  # type: ignore[no-untyped-call]

    assistant_msg = outcome.get("assistant_message", "")
    if assistant_msg:
        await cl.Message(content=assistant_msg).send()  # type: ignore[no-untyped-call]
    else:
        status_label = "APPROVED" if decision == "APPROVE" else "REJECTED"
        summary_md = format_remediation_summary(result, status_label)
        await cl.Message(content=summary_md).send()  # type: ignore[no-untyped-call]


@cl.action_callback("approve_action")
async def on_approve(action: cl.Action) -> None:
    """Handle explicit human approval to execute the pending remediation."""
    await _handle_operator_decision(action, "APPROVE")


@cl.action_callback("reject_action")
async def on_reject(action: cl.Action) -> None:
    """Handle operator rejection to abort the pending remediation safely."""
    await _handle_operator_decision(action, "REJECT")
