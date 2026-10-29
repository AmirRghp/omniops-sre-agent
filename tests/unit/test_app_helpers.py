"""Unit tests for UI helper formatting and HITL card generation."""

from src.agent.ui_helpers import (
    format_approval_card,
    format_remediation_summary,
    format_step_header,
    format_welcome_message,
    get_mode_badge,
)


def test_get_mode_badge_live() -> None:
    badge = get_mode_badge("LIVE_OMNIDOC_RAG")
    assert "Live OmniDoc RAG" in badge
    assert "🟢" in badge


def test_get_mode_badge_fallback() -> None:
    badge = get_mode_badge("LOCAL_FALLBACK")
    assert "Local Fallback Runbook" in badge
    assert "🟡" in badge


def test_get_mode_badge_none() -> None:
    assert get_mode_badge(None) == ""
    assert get_mode_badge("OTHER") == ""


def test_format_step_header_read_tool_with_fallback() -> None:
    header = format_step_header(
        tool_name="search_runbooks",
        duration_ms=45.2,
        source_mode="LOCAL_FALLBACK",
        is_error=False,
    )
    assert "search_runbooks" in header
    assert "[Read-Only]" in header
    assert "45ms" in header
    assert "Local Fallback Runbook" in header


def test_format_step_header_write_tool() -> None:
    header = format_step_header(
        tool_name="execute_remediation",
        duration_ms=120.0,
        source_mode=None,
        is_error=False,
    )
    assert "execute_remediation" in header
    assert "[Write-Gated]" in header
    assert "120ms" in header


def test_format_step_header_error() -> None:
    header = format_step_header(
        tool_name="get_service_health",
        duration_ms=15.0,
        source_mode=None,
        is_error=True,
    )
    assert "[Read-Only]" in header
    assert "Self-Correcting" in header or "Tool Error" in header


def test_format_approval_card() -> None:
    pending = {
        "tool_call_id": "call_123",
        "service_name": "payment-api",
        "action_type": "increase_db_pool",
        "parameters": {"pool_size": 200},
        "idempotency_key": "idem_test_999",
        "reason": "QueuePool limit of size 100 reached per RB-104",
    }
    card = format_approval_card(pending)

    assert "⚠️ نیاز به تایید اپراتور" in card
    assert "Human Approval Required" in card
    assert "payment-api" in card
    assert "increase_db_pool" in card
    assert "idem_test_999" in card
    assert "RB-104" in card
    assert '"pool_size": 200' in card or "pool_size" in card


def test_format_welcome_message() -> None:
    welcome = format_welcome_message()
    assert "OmniOps SRE Agent" in welcome
    assert "payment-api" in welcome
    assert "redis-cache" in welcome


def test_format_remediation_summary_approved() -> None:
    result = {
        "status": "success",
        "idempotent_replay": False,
        "service_name": "payment-api",
        "action_type": "increase_db_pool",
        "details": {"previous_pool_size": 100, "new_pool_size": 200},
    }
    summary = format_remediation_summary(result, "APPROVED")
    assert "تایید" in summary or "موفق" in summary
    assert "payment-api" in summary


def test_format_remediation_summary_rejected() -> None:
    result = {
        "status": "REJECTED_BY_OPERATOR",
        "reason": "Peak traffic window",
    }
    summary = format_remediation_summary(result, "REJECTED")
    assert "لغو" in summary or "رد" in summary
    assert "Peak traffic window" in summary
