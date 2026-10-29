"""Pydantic request schemas for the OmniOps FastAPI layer."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class IncidentStreamRequest(BaseModel):
    """Start or inspect an incident investigation stream."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    query: str = Field(
        ...,
        min_length=1,
        description="Incident description in Persian or English.",
    )
    thread_id: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="LangGraph thread identifier for this incident.",
    )


class ApprovalRequest(BaseModel):
    """Human decision for a paused remediation gate."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    thread_id: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="LangGraph thread identifier awaiting approval.",
    )
    decision: Literal["APPROVE", "REJECT"] = Field(
        ...,
        description="Operator decision for the pending remediation.",
    )
    operator_id: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Operator identity recorded in the audit trail.",
    )
    comment: str = Field(
        default="",
        max_length=1000,
        description="Optional operator note explaining the decision.",
    )
