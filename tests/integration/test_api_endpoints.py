"""Integration tests for the FastAPI streaming, approval, and reset endpoints."""

import json
import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from langchain_core.messages import HumanMessage
from sqlalchemy import select

from main import app
from src.agent import nodes
from src.agent.graph import postgres_graph
from src.db.models import InfraService, RemediationExecution
from src.db.seed import reset_database
from src.db.session import session_scope

SSE_HEADERS = {"content-type": "text/event-stream"}


@pytest.fixture(autouse=True)
async def reset_state() -> None:
    """Reset operational tables before each test for deterministic state."""
    await reset_database()


class _ScriptedCompletions:
    def __init__(self, completions: list[Any]) -> None:
        self._completions = completions
        self.calls = 0

    async def create(self, **kwargs: Any) -> Any:
        self.calls += 1
        return self._completions.pop(0)


class _ScriptedClient:
    def __init__(self, completions: list[Any]) -> None:
        self.chat = SimpleNamespace(completions=_ScriptedCompletions(completions))


def _completion(content: str, tool_calls: list[Any] | None = None) -> Any:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=tool_calls or []))
        ],
        usage=SimpleNamespace(total_tokens=100),
    )


def _tool_call(call_id: str, name: str, arguments: dict[str, Any]) -> Any:
    return SimpleNamespace(
        type="function",
        id=call_id,
        function=SimpleNamespace(name=name, arguments=json.dumps(arguments)),
    )


def _health_completion() -> Any:
    return _completion(
        "Checking payment-api health.",
        [_tool_call("call_health_1", "get_service_health", {"service_name": "payment-api"})],
    )


def _remediation_completion(idempotency_key: str) -> Any:
    return _completion(
        "Proposing a pool increase.",
        [
            _tool_call(
                "call_remediation_1",
                "execute_remediation",
                {
                    "service_name": "payment-api",
                    "action_type": "increase_db_pool",
                    "parameters": {"pool_size": 200},
                    "idempotency_key": idempotency_key,
                    "reason": "ERR_DB_POOL_EXHAUSTED per RB-104",
                },
            )
        ],
    )


def _final_completion() -> Any:
    return _completion("Incident resolved after the pool increase.")


def _use_script(monkeypatch: pytest.MonkeyPatch, completions: list[Any]) -> _ScriptedClient:
    client = _ScriptedClient(completions)
    monkeypatch.setattr(nodes, "_get_llm_client", lambda: client)
    return client


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _parse_sse(text: str) -> list[tuple[str, dict[str, Any]]]:
    """Decode the raw SSE body into (event, payload) pairs."""
    events: list[tuple[str, dict[str, Any]]] = []
    for block in text.split("\n\n"):
        if not block.strip():
            continue
        name = ""
        data = ""
        for line in block.splitlines():
            if line.startswith("event:"):
                name = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data += line[len("data:") :].strip()
        events.append((name, json.loads(data) if data else {}))
    return events


async def _service_snapshot() -> dict[str, Any]:
    async with session_scope() as session:
        service = await session.get(InfraService, "payment-api")
        assert service is not None
        return {
            "status": service.status,
            "db_pool_size": service.db_pool_size,
            "p95_latency_ms": service.p95_latency_ms,
        }


async def _audit_records() -> list[dict[str, Any]]:
    async with session_scope() as session:
        result = await session.execute(select(RemediationExecution))
        return [
            {
                "idempotency_key": record.idempotency_key,
                "thread_id": record.thread_id,
                "approved_by": record.approved_by,
                "approval_status": record.approval_status,
            }
            for record in result.scalars().all()
        ]


async def _open_paused_thread(
    monkeypatch: pytest.MonkeyPatch,
    thread_id: str,
) -> tuple[list[tuple[str, dict[str, Any]]], str]:
    """Drive the graph up to the HITL gate through the streaming endpoint."""
    idempotency_key = f"idem_api_{uuid.uuid4().hex[:12]}"
    _use_script(monkeypatch, [_health_completion(), _remediation_completion(idempotency_key)])
    async with _client() as client:
        response = await client.post(
            "/api/v1/incident/stream",
            json={"query": "payment-api is degraded with pool exhaustion.", "thread_id": thread_id},
        )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith(SSE_HEADERS["content-type"])
    return _parse_sse(response.text), idempotency_key


@pytest.mark.asyncio
async def test_stream_emits_tool_events_and_halts_for_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify the stream reports tool progress and stops at the approval gate."""
    thread_id = f"inc_api_{uuid.uuid4().hex}"
    events, _ = await _open_paused_thread(monkeypatch, thread_id)
    names = [name for name, _ in events]

    assert names[0] == "token"
    assert {"tool_call", "tool_result", "approval_required", "done"} <= set(names)
    assert names[-2:] == ["approval_required", "done"]

    payloads = [data for name, data in events if name == "tool_call"]
    assert payloads[0]["name"] == "get_service_health"
    assert payloads[0]["arguments"] == {"service_name": "payment-api"}
    assert payloads[1]["name"] == "execute_remediation"

    tool_result = next(data for name, data in events if name == "tool_result")
    assert tool_result["result"]["status"] == "success"
    assert tool_result["result"]["service"]["health_status"] == "DEGRADED"

    approval = events[-2][1]["pending_remediation"]
    assert approval["service_name"] == "payment-api"
    assert approval["action_type"] == "increase_db_pool"
    assert approval["parameters"] == {"pool_size": 200}

    done = events[-1][1]
    assert done["status"] == "AWAITING_APPROVAL"
    assert done["step_count"] == 2

    assert await _service_snapshot() == {
        "status": "DEGRADED",
        "db_pool_size": 100,
        "p95_latency_ms": 4200,
    }
    assert await _audit_records() == []


@pytest.mark.asyncio
async def test_stream_reports_pending_approval_without_new_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify a paused thread returns the gate instead of running the agent again."""
    thread_id = f"inc_api_{uuid.uuid4().hex}"
    await _open_paused_thread(monkeypatch, thread_id)

    script = _use_script(monkeypatch, [])
    async with _client() as client:
        response = await client.post(
            "/api/v1/incident/stream",
            json={"query": "please continue without approval", "thread_id": thread_id},
        )

    body = _parse_sse(response.text)
    assert [name for name, _ in body] == ["approval_required", "done"]
    assert body[-1][1]["status"] == "AWAITING_APPROVAL"
    assert script.chat.completions.calls == 0

    async with postgres_graph() as graph:
        snapshot = await graph.aget_state({"configurable": {"thread_id": thread_id}})
    assert not any(
        isinstance(message, HumanMessage) and message.content == "please continue without approval"
        for message in snapshot.values["messages"]
    )
    assert snapshot.next == ("remediation_node",)


@pytest.mark.asyncio
async def test_approve_endpoint_executes_and_records_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify an approval resumes the graph and mutates the target service once."""
    thread_id = f"inc_api_{uuid.uuid4().hex}"
    _, idempotency_key = await _open_paused_thread(monkeypatch, thread_id)
    _use_script(monkeypatch, [_final_completion()])

    async with _client() as client:
        response = await client.post(
            "/api/v1/incident/approve",
            json={
                "thread_id": thread_id,
                "decision": "APPROVE",
                "operator_id": "sre_admin",
                "comment": "Verified RB-104",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["approval_status"] == "APPROVED"
    assert body["result"]["idempotent_replay"] is False
    assert body["assistant_message"] == "Incident resolved after the pool increase."

    assert await _service_snapshot() == {
        "status": "HEALTHY",
        "db_pool_size": 200,
        "p95_latency_ms": 140,
    }
    audit = await _audit_records()
    assert len(audit) == 1
    assert audit[0]["idempotency_key"] == idempotency_key
    assert audit[0]["thread_id"] == thread_id
    assert audit[0]["approved_by"] == "sre_admin"
    assert audit[0]["approval_status"] == "APPROVED"


@pytest.mark.asyncio
async def test_reject_endpoint_leaves_infrastructure_untouched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify a rejection resumes the graph without mutating infrastructure."""
    thread_id = f"inc_api_{uuid.uuid4().hex}"
    await _open_paused_thread(monkeypatch, thread_id)
    _use_script(monkeypatch, [_final_completion()])

    async with _client() as client:
        response = await client.post(
            "/api/v1/incident/approve",
            json={
                "thread_id": thread_id,
                "decision": "REJECT",
                "operator_id": "sre_admin",
                "comment": "Peak traffic window",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["approval_status"] == "REJECTED"
    assert body["result"]["status"] == "REJECTED_BY_OPERATOR"
    assert body["result"]["reason"] == "Peak traffic window"

    assert await _service_snapshot() == {
        "status": "DEGRADED",
        "db_pool_size": 100,
        "p95_latency_ms": 4200,
    }
    assert await _audit_records() == []


@pytest.mark.asyncio
async def test_approve_rejects_unknown_or_malformed_requests() -> None:
    """Verify missing threads and unsupported decisions fail at the API boundary."""
    async with _client() as client:
        missing = await client.post(
            "/api/v1/incident/approve",
            json={
                "thread_id": f"inc_missing_{uuid.uuid4().hex}",
                "decision": "APPROVE",
                "operator_id": "sre_admin",
            },
        )
        malformed = await client.post(
            "/api/v1/incident/approve",
            json={"thread_id": "inc_any", "decision": "MAYBE", "operator_id": "sre_admin"},
        )
        blank_query = await client.post(
            "/api/v1/incident/stream",
            json={"query": "   ", "thread_id": "inc_any"},
        )

    assert missing.status_code == 404
    assert missing.json()["detail"]["error_code"] == "NO_PENDING_REMEDIATION"
    assert malformed.status_code == 422
    assert blank_query.status_code == 422


@pytest.mark.asyncio
async def test_reset_endpoint_restores_seed_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify the reset endpoint clears audit history and re-seeds infrastructure."""
    thread_id = f"inc_api_{uuid.uuid4().hex}"
    await _open_paused_thread(monkeypatch, thread_id)
    _use_script(monkeypatch, [_final_completion()])

    async with _client() as client:
        approved = await client.post(
            "/api/v1/incident/approve",
            json={"thread_id": thread_id, "decision": "APPROVE", "operator_id": "sre_admin"},
        )
        assert approved.status_code == 200
        assert await _audit_records() != []

        reset = await client.post("/api/v1/infra/reset")

    assert reset.status_code == 200
    assert reset.json()["status"] == "success"
    assert await _service_snapshot() == {
        "status": "DEGRADED",
        "db_pool_size": 100,
        "p95_latency_ms": 4200,
    }
    assert await _audit_records() == []
