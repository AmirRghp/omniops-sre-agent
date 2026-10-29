"""Integration tests for the LangGraph HITL interrupt and resume flow."""

import json
import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from langchain_core.messages import HumanMessage, ToolMessage
from sqlalchemy import select

from src.agent import nodes
from src.agent.graph import postgres_graph, resume_with_approval
from src.agent.state import IncidentState
from src.db.models import InfraService, RemediationExecution
from src.db.seed import reset_database
from src.db.session import session_scope


@pytest.fixture(autouse=True)
async def reset_state() -> None:
    """Reset operational tables before each test for deterministic state."""
    await reset_database()


class _ScriptedCompletions:
    def __init__(self, completions: list[Any]) -> None:
        self._completions = completions

    async def create(self, **kwargs: Any) -> Any:
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


def _remediation_completion(idempotency_key: str) -> Any:
    call = SimpleNamespace(
        type="function",
        id="call_remediation_1",
        function=SimpleNamespace(
            name="execute_remediation",
            arguments=json.dumps(
                {
                    "service_name": "payment-api",
                    "action_type": "increase_db_pool",
                    "parameters": {"pool_size": 200},
                    "idempotency_key": idempotency_key,
                    "reason": "ERR_DB_POOL_EXHAUSTED per RB-104",
                }
            ),
        ),
    )
    return _completion("Proposing remediation.", [call])


def _patch_llm(monkeypatch: pytest.MonkeyPatch, idempotency_key: str) -> None:
    script = _ScriptedClient(
        [_remediation_completion(idempotency_key), _completion("Incident resolved.")]
    )
    monkeypatch.setattr(nodes, "_get_llm_client", lambda: script)


def _initial_state() -> IncidentState:
    return {
        "messages": [HumanMessage(content="payment-api is degraded due to pool exhaustion.")],
        "step_count": 0,
        "tokens_used": 0,
        "pending_remediation": None,
        "approval_status": None,
        "approved_by": None,
        "approval_comment": None,
        "fallback_used": False,
    }


def _config(thread_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": thread_id}}


async def _service_snapshot(service_name: str) -> dict[str, Any]:
    async with session_scope() as session:
        service = await session.get(InfraService, service_name)
        assert service is not None
        return {
            "status": service.status,
            "db_pool_size": service.db_pool_size,
            "p95_latency_ms": service.p95_latency_ms,
        }


async def _audit_snapshots() -> list[dict[str, Any]]:
    async with session_scope() as session:
        result = await session.execute(
            select(RemediationExecution).order_by(RemediationExecution.created_at)
        )
        return [
            {
                "idempotency_key": record.idempotency_key,
                "thread_id": record.thread_id,
                "approved_by": record.approved_by,
                "approval_status": record.approval_status,
            }
            for record in result.scalars().all()
        ]


@pytest.mark.asyncio
async def test_graph_interrupts_and_executes_after_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify the graph pauses before remediation and executes once after approval."""
    thread_id = f"inc_test_{uuid.uuid4().hex}"
    idempotency_key = f"idem_test_{uuid.uuid4().hex[:12]}"
    _patch_llm(monkeypatch, idempotency_key)
    config = _config(thread_id)

    async with postgres_graph() as graph:
        await graph.ainvoke(_initial_state(), config)
        snapshot = await graph.aget_state(config)

    assert snapshot.next == ("remediation_node",)
    assert snapshot.values["approval_status"] == "PENDING"
    assert snapshot.values["pending_remediation"]["service_name"] == "payment-api"

    before = await _service_snapshot("payment-api")
    assert before == {"status": "DEGRADED", "db_pool_size": 100, "p95_latency_ms": 4200}
    assert await _audit_snapshots() == []

    outcome = await resume_with_approval(
        thread_id,
        "APPROVE",
        "sre_admin",
        "Verified RB-104",
    )
    assert outcome["status"] == "success"
    assert outcome["approval_status"] == "APPROVED"
    assert outcome["result"]["status"] == "success"
    assert outcome["result"]["idempotent_replay"] is False

    after = await _service_snapshot("payment-api")
    assert after == {"status": "HEALTHY", "db_pool_size": 200, "p95_latency_ms": 140}

    audit = await _audit_snapshots()
    assert len(audit) == 1
    assert audit[0]["idempotency_key"] == idempotency_key
    assert audit[0]["thread_id"] == thread_id
    assert audit[0]["approved_by"] == "sre_admin"
    assert audit[0]["approval_status"] == "APPROVED"

    async with postgres_graph() as graph:
        final_snapshot = await graph.aget_state(config)
    assert final_snapshot.next == ()
    assert final_snapshot.values["approval_status"] == "APPROVED"
    assert final_snapshot.values["pending_remediation"] is None
    assert any(
        isinstance(message, ToolMessage) and message.tool_call_id == "call_remediation_1"
        for message in final_snapshot.values["messages"]
    )

    second = await resume_with_approval(thread_id, "APPROVE", "sre_admin", "")
    assert second["status"] == "error"
    assert second["error_code"] == "NO_PENDING_REMEDIATION"
    assert len(await _audit_snapshots()) == 1


@pytest.mark.asyncio
async def test_rejection_injects_tool_message_without_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify rejection records a ToolMessage and leaves infrastructure untouched."""
    thread_id = f"inc_test_{uuid.uuid4().hex}"
    idempotency_key = f"idem_test_{uuid.uuid4().hex[:12]}"
    _patch_llm(monkeypatch, idempotency_key)
    config = _config(thread_id)

    async with postgres_graph() as graph:
        await graph.ainvoke(_initial_state(), config)
        snapshot = await graph.aget_state(config)
    assert snapshot.next == ("remediation_node",)

    outcome = await resume_with_approval(
        thread_id,
        "REJECT",
        "sre_admin",
        "Peak traffic window",
    )
    assert outcome["status"] == "success"
    assert outcome["approval_status"] == "REJECTED"
    assert outcome["result"]["status"] == "REJECTED_BY_OPERATOR"
    assert outcome["result"]["reason"] == "Peak traffic window"

    after = await _service_snapshot("payment-api")
    assert after == {"status": "DEGRADED", "db_pool_size": 100, "p95_latency_ms": 4200}
    assert await _audit_snapshots() == []

    async with postgres_graph() as graph:
        final_snapshot = await graph.aget_state(config)
    assert final_snapshot.next == ()
    assert final_snapshot.values["approval_status"] == "REJECTED"
    assert final_snapshot.values["pending_remediation"] is None
    rejection_messages = [
        message
        for message in final_snapshot.values["messages"]
        if isinstance(message, ToolMessage) and message.tool_call_id == "call_remediation_1"
    ]
    assert rejection_messages
    assert json.loads(rejection_messages[0].content)["status"] == "REJECTED_BY_OPERATOR"


@pytest.mark.asyncio
async def test_resume_rejects_invalid_decision() -> None:
    """Verify unsupported decisions fail before touching thread state."""
    outcome = await resume_with_approval("any_thread", "MAYBE", "sre_admin", "")
    assert outcome["status"] == "error"
    assert outcome["error_code"] == "INVALID_DECISION"
    assert outcome["valid_decisions"] == ["APPROVE", "REJECT"]
