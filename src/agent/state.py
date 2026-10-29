"""Shared LangGraph state contract for the OmniOps incident agent."""

from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

from src.mcp_server.schemas import RemediationActionType

ApprovalStatus = Literal["PENDING", "APPROVED", "REJECTED"]


class PendingRemediation(TypedDict):
    """Proposed write action awaiting the human-in-the-loop approval gate."""

    tool_call_id: str
    service_name: str
    action_type: RemediationActionType
    parameters: dict[str, Any]
    idempotency_key: str
    reason: str


class IncidentState(TypedDict):
    """Durable per-incident state persisted in the LangGraph checkpoint store."""

    messages: Annotated[list[AnyMessage], add_messages]
    step_count: int
    tokens_used: int
    pending_remediation: PendingRemediation | None
    approval_status: ApprovalStatus | None
    fallback_used: bool
