"""LangGraph nodes for the OmniOps incident reasoning loop."""

import asyncio
import json
import re
import uuid
from functools import lru_cache
from typing import Any, cast

from langchain_core.messages import AIMessage, ToolCall, ToolMessage
from langchain_core.messages.utils import convert_to_openai_messages
from langchain_core.runnables import RunnableConfig
from openai import AsyncOpenAI
from openai.types.chat import (
    ChatCompletionMessage,
    ChatCompletionMessageParam,
    ChatCompletionToolParam,
)
from pydantic import BaseModel

from src.agent.state import IncidentState, PendingRemediation
from src.common.config import get_settings, load_yaml_config
from src.common.logger import setup_logger
from src.mcp_server import tools
from src.mcp_server.schemas import (
    ExecuteRemediationInput,
    GetServiceHealthInput,
    QueryIncidentLogsInput,
    SearchRunbooksInput,
    ToolErrorResponse,
)

logger = setup_logger("agent_nodes")

READ_ONLY_TOOLS = frozenset({"search_runbooks", "query_incident_logs", "get_service_health"})


def _load_tool_timeout() -> float:
    """Read tool execution timeout from configs/config.yaml with a safe default."""
    try:
        cfg = load_yaml_config("configs/config.yaml")
        return float(cfg.get("tools", {}).get("execution_timeout_seconds", 5.0))
    except Exception:
        return 5.0


TOOL_TIMEOUT_SECONDS = _load_tool_timeout()


def _tool_definition(
    name: str,
    description: str,
    input_model: type[BaseModel],
    required: list[str] | None = None,
) -> dict[str, Any]:
    """Build an OpenAI function definition from an existing Pydantic tool schema."""
    parameters = input_model.model_json_schema()
    if required is not None:
        parameters["required"] = required
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": parameters,
        },
    }


MCP_TOOL_DEFINITIONS: list[dict[str, Any]] = [
    _tool_definition(
        "search_runbooks",
        "Search troubleshooting runbooks via OmniDoc RAG or the local fallback.",
        SearchRunbooksInput,
    ),
    _tool_definition(
        "query_incident_logs",
        "Fetch recent structured logs for a specific microservice from PostgreSQL.",
        QueryIncidentLogsInput,
    ),
    _tool_definition(
        "get_service_health",
        "Retrieve real-time resource utilization, replica counts, connection pools, and status.",
        GetServiceHealthInput,
    ),
    _tool_definition(
        "execute_remediation",
        (
            "Submit a proposed remediation action for human review and execution. "
            "You MUST invoke this tool whenever a remediation action is required. "
            "Invoking this tool automatically pauses execution and triggers the approval gate."
        ),
        ExecuteRemediationInput,
        required=[
            "service_name",
            "action_type",
            "parameters",
            "idempotency_key",
            "reason",
        ],
    ),
]

_system_prompt_cache: str | None = None


async def _get_system_prompt() -> str:
    """Load and cache the SRE system prompt without blocking the event loop."""
    global _system_prompt_cache
    if _system_prompt_cache is None:
        config = await asyncio.to_thread(load_yaml_config, "configs/prompts.yaml")
        _system_prompt_cache = str(config["system_prompt"])
    return _system_prompt_cache


@lru_cache(maxsize=1)
def _get_llm_client() -> AsyncOpenAI:
    """Provide a cached async client for the local vLLM OpenAI-compatible endpoint."""
    settings = get_settings()
    return AsyncOpenAI(base_url=settings.LLM_BASE_URL, api_key=settings.LLM_API_KEY)


def _parse_tool_arguments(raw_arguments: str) -> dict[str, Any]:
    """Parse model-generated JSON arguments, returning an empty mapping when invalid."""
    try:
        parsed = json.loads(raw_arguments)
    except (json.JSONDecodeError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _extract_json_objects(raw_text: str) -> list[dict[str, Any]]:
    """Extract all valid JSON objects from text, handling nested braces and code fences."""
    results: list[dict[str, Any]] = []
    fence_pattern = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
    for match in fence_pattern.finditer(raw_text):
        try:
            parsed = json.loads(match.group(1))
            if isinstance(parsed, dict):
                results.append(parsed)
        except Exception:
            pass

    start_idx = None
    depth = 0
    in_string = False
    escape = False

    for i, char in enumerate(raw_text):
        if escape:
            escape = False
            continue
        if char == "\\":
            escape = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue

        if char == "{":
            if depth == 0:
                start_idx = i
            depth += 1
        elif char == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start_idx is not None:
                    candidate = raw_text[start_idx : i + 1]
                    try:
                        parsed = json.loads(candidate)
                        if isinstance(parsed, dict) and parsed not in results:
                            results.append(parsed)
                    except Exception:
                        pass
                    start_idx = None

    return results


def _extract_tool_calls_from_text(content: str) -> list[ToolCall]:
    """Fallback extractor when model emits tool calls or remediation actions in text."""
    calls: list[ToolCall] = []
    known_tools = {
        "execute_remediation",
        "search_runbooks",
        "query_incident_logs",
        "get_service_health",
    }
    action_types = {
        "increase_db_pool",
        "scale_replicas",
        "restart_service",
        "flush_redis_cache",
    }

    objects = _extract_json_objects(content)
    for obj in objects:
        name = obj.get("name")
        if name in known_tools:
            raw_args = obj.get("arguments", {})
            args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            if isinstance(args, dict):
                calls.append(
                    {
                        "name": str(name),
                        "args": args,
                        "id": f"call_text_{uuid.uuid4().hex[:8]}",
                        "type": "tool_call",
                    }
                )
                continue

        action = obj.get("action_type")
        if action in action_types:
            service = obj.get("service_name")
            if not service:
                known_services = (
                    "payment-api",
                    "auth-service",
                    "postgres-primary",
                    "redis-cache",
                    "nginx-ingress",
                )
                for s in known_services:
                    if s in content:
                        service = s
                        break
                obj["service_name"] = service or "payment-api"
            if "parameters" not in obj or not isinstance(obj["parameters"], dict):
                obj["parameters"] = {}
            if "idempotency_key" not in obj:
                uid = uuid.uuid4().hex[:6]
                obj["idempotency_key"] = f"idem_{obj['service_name']}_{action}_{uid}"
            if "reason" not in obj:
                obj["reason"] = f"Remediation for {obj['service_name']} via {action}"
            calls.append(
                {
                    "name": "execute_remediation",
                    "args": obj,
                    "id": f"call_text_{uuid.uuid4().hex[:8]}",
                    "type": "tool_call",
                }
            )

    return calls


def _to_ai_message(message: ChatCompletionMessage) -> AIMessage:
    """Convert the OpenAI completion message into a LangChain AI message with tool calls."""
    tool_calls: list[ToolCall] = []
    for call in message.tool_calls or []:
        if call.type != "function":
            continue
        tool_calls.append(
            {
                "name": call.function.name,
                "args": _parse_tool_arguments(call.function.arguments),
                "id": call.id,
                "type": "tool_call",
            }
        )
    if not tool_calls and message.content:
        tool_calls = _extract_tool_calls_from_text(message.content)

    return AIMessage(content=message.content or "", tool_calls=tool_calls)


def _extract_pending_remediation(tool_calls: list[ToolCall]) -> PendingRemediation | None:
    """Capture the first proposed write action for the human approval gate."""
    for call in tool_calls:
        if call["name"] != "execute_remediation":
            continue
        arguments = call["args"]
        raw_parameters = arguments.get("parameters")
        parameters: dict[str, Any] = raw_parameters if isinstance(raw_parameters, dict) else {}
        return {
            "tool_call_id": call["id"] or "",
            "service_name": str(arguments.get("service_name", "")),
            "action_type": arguments.get("action_type", ""),
            "parameters": parameters,
            "idempotency_key": str(arguments.get("idempotency_key", "")),
            "reason": str(arguments.get("reason", "")),
        }
    return None


async def agent_reasoning_node(state: IncidentState) -> dict[str, Any]:
    """Call vLLM with the SRE prompt and narrow tool definitions, then record the turn."""
    settings = get_settings()
    system_prompt = await _get_system_prompt()
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        *convert_to_openai_messages(state["messages"]),
    ]
    completion = await _get_llm_client().chat.completions.create(
        model=settings.LLM_MODEL_NAME,
        messages=cast(list[ChatCompletionMessageParam], messages),
        tools=cast(list[ChatCompletionToolParam], MCP_TOOL_DEFINITIONS),
        temperature=0,
    )

    ai_message = _to_ai_message(completion.choices[0].message)
    total_tokens = completion.usage.total_tokens if completion.usage else 0
    update: dict[str, Any] = {
        "messages": [ai_message],
        "step_count": state.get("step_count", 0) + 1,
        "tokens_used": max(state.get("tokens_used", 0), total_tokens),
    }

    pending_remediation = _extract_pending_remediation(ai_message.tool_calls)
    if pending_remediation is not None:
        update["pending_remediation"] = pending_remediation
        update["approval_status"] = "PENDING"
        update["approved_by"] = None
        update["approval_comment"] = None

    return update


def _tool_error(error_code: str, message: str) -> dict[str, Any]:
    """Build a structured tool error that the LLM can reason about."""
    return ToolErrorResponse(error_code=error_code, message=message).model_dump()


async def _execute_read_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Dispatch a read-only tool by its MCP name."""
    if name == "search_runbooks":
        return await tools.search_runbooks(**arguments)
    if name == "query_incident_logs":
        return await tools.query_incident_logs(**arguments)
    if name == "get_service_health":
        return await tools.get_service_health(**arguments)
    return _tool_error("UNKNOWN_TOOL", f"Tool '{name}' is not a read-only diagnostic tool.")


async def _run_read_tool_call(call: ToolCall) -> tuple[ToolMessage, dict[str, Any]]:
    """Execute one read tool with a hard timeout and convert failures to ToolMessages."""
    name = call["name"]
    tool_call_id = call["id"] or ""
    try:
        result = await asyncio.wait_for(
            _execute_read_tool(name, call["args"]),
            timeout=TOOL_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        logger.error("Read tool %s timed out after %.1fs", name, TOOL_TIMEOUT_SECONDS)
        result = _tool_error(
            "TOOL_TIMEOUT",
            f"Tool '{name}' timed out after {TOOL_TIMEOUT_SECONDS:g} seconds.",
        )
    except Exception as exc:
        logger.error("Read tool %s failed: %s", name, exc)
        result = _tool_error(
            "TOOL_EXECUTION_ERROR",
            f"Tool '{name}' encountered an internal execution error.",
        )

    return (
        ToolMessage(
            content=json.dumps(result, ensure_ascii=False, default=str),
            tool_call_id=tool_call_id,
            name=name,
        ),
        result,
    )


async def read_tools_node(state: IncidentState) -> dict[str, Any]:
    """Execute all pending read-only tool calls concurrently."""
    ai_message = next(
        (message for message in reversed(state["messages"]) if isinstance(message, AIMessage)),
        None,
    )
    if ai_message is None:
        return {"messages": []}

    answered_ids = {
        message.tool_call_id for message in state["messages"] if isinstance(message, ToolMessage)
    }
    read_calls = [
        call
        for call in ai_message.tool_calls
        if call["name"] in READ_ONLY_TOOLS and call["id"] not in answered_ids
    ]
    if not read_calls:
        return {"messages": []}

    executions = await asyncio.gather(*(_run_read_tool_call(call) for call in read_calls))
    update: dict[str, Any] = {
        "messages": [tool_message for tool_message, _ in executions],
    }
    if any(result.get("source_mode") == "LOCAL_FALLBACK" for _, result in executions):
        update["fallback_used"] = True
    return update


async def remediation_node(state: IncidentState, config: RunnableConfig) -> dict[str, Any]:
    """Execute or reject the pending remediation after the human approval gate."""
    pending = state.get("pending_remediation")
    if pending is None:
        return {}

    tool_call_id = pending["tool_call_id"]
    approval_status = state.get("approval_status")

    if approval_status == "APPROVED":
        configurable = config.get("configurable", {})
        thread_id = str(configurable.get("thread_id") or "unknown")
        try:
            result = await asyncio.wait_for(
                tools.execute_remediation(
                    service_name=pending["service_name"],
                    action_type=pending["action_type"],
                    parameters=pending["parameters"],
                    idempotency_key=pending["idempotency_key"],
                    reason=pending["reason"],
                    thread_id=thread_id,
                    approved_by=state.get("approved_by"),
                ),
                timeout=TOOL_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            logger.error("Remediation timed out after %.1fs", TOOL_TIMEOUT_SECONDS)
            result = _tool_error(
                "TOOL_TIMEOUT",
                f"Remediation timed out after {TOOL_TIMEOUT_SECONDS:g} seconds.",
            )
        except Exception as exc:
            logger.error("Remediation failed: %s", exc)
            result = _tool_error(
                "TOOL_EXECUTION_ERROR",
                "Remediation encountered an internal execution error.",
            )
    elif approval_status == "REJECTED":
        result = {
            "status": "REJECTED_BY_OPERATOR",
            "reason": state.get("approval_comment") or "Rejected by operator.",
        }
    else:
        result = _tool_error(
            "APPROVAL_REQUIRED",
            "Remediation requires an explicit human approval decision.",
        )

    return {
        "messages": [
            ToolMessage(
                content=json.dumps(result, ensure_ascii=False, default=str),
                tool_call_id=tool_call_id,
                name="execute_remediation",
            )
        ],
        "pending_remediation": None,
    }


async def force_terminate_node(state: IncidentState) -> dict[str, Any]:
    """Stop the agent at a hard ceiling and hand the incident to a human operator."""
    settings = get_settings()
    step_count = state.get("step_count", 0)
    tokens_used = state.get("tokens_used", 0)
    if tokens_used >= settings.MAX_AGENT_TOKENS:
        budget = f"Token budget exhausted ({tokens_used}/{settings.MAX_AGENT_TOKENS})"
    else:
        budget = f"Step budget exhausted ({step_count}/{settings.MAX_AGENT_STEPS})"

    return {
        "messages": [
            AIMessage(
                content=(
                    f"{budget}. Stopped before proposing or executing further actions. "
                    "Review the collected tool outputs, confirm the root cause, and escalate "
                    "to a human SRE for manual remediation."
                )
            )
        ]
    }
