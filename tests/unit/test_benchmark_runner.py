"""Unit tests for the quantitative benchmark runner and fault injection suite."""

from evals.fault_injection import FaultInjector, FaultType
from evals.run_agent_benchmark import (
    ScenarioResult,
    compute_benchmark_report,
    generate_comparison_table,
    generate_markdown_report,
    run_dry_run_scenario,
    validate_tool_arguments,
)


def test_fault_injector_mechanics() -> None:
    injector = FaultInjector()
    assert injector.total_injected == 0
    assert injector.recovery_rate == 100.0

    err_service = injector.create_fault_response(
        tool_name="get_service_health",
        fault_type=FaultType.SERVICE_NOT_FOUND,
        attempted_service="payment-service",
    )
    assert err_service["status"] == "error"
    assert err_service["error_code"] == "SERVICE_NOT_FOUND"
    assert "payment-api" in err_service["valid_services"]

    err_timeout = injector.create_fault_response(
        tool_name="search_runbooks",
        fault_type=FaultType.TOOL_TIMEOUT,
    )
    assert err_timeout["error_code"] == "TOOL_TIMEOUT"

    err_transient = injector.create_fault_response(
        tool_name="query_incident_logs",
        fault_type=FaultType.TRANSIENT_ERROR,
    )
    assert err_transient["error_code"] == "TOOL_EXECUTION_ERROR"

    assert injector.total_injected == 3
    assert injector.total_recovered == 0
    assert injector.recovery_rate == 0.0

    injector.mark_recovery(0, True)
    injector.mark_recovery(1, True)
    assert injector.total_recovered == 2
    assert round(injector.recovery_rate, 1) == 66.7


def test_validate_tool_arguments() -> None:
    # Valid get_service_health
    assert validate_tool_arguments("get_service_health", {"service_name": "payment-api"})
    # Missing required argument
    assert not validate_tool_arguments("get_service_health", {})

    # Valid search_runbooks
    assert validate_tool_arguments("search_runbooks", {"query": "redis OOM"})
    # Extra unexpected arguments forbidden
    assert not validate_tool_arguments(
        "search_runbooks", {"query": "test", "extra_hallucinated_param": True}
    )

    # Valid execute_remediation
    assert validate_tool_arguments(
        "execute_remediation",
        {
            "service_name": "payment-api",
            "action_type": "increase_db_pool",
            "parameters": {"db_pool_size": 200},
            "idempotency_key": "idem_123",
            "reason": "pool saturation",
        },
    )

    # Unknown tool
    assert not validate_tool_arguments("unknown_tool", {})


def test_dry_run_scenarios_and_report_7b() -> None:
    scenario = {
        "scenario_id": "SCN-01",
        "name": "Payment API DB Pool Exhaustion Triage",
        "category": "db_pool_exhaustion",
        "language": "fa",
        "prompt": "سرویس payment-api کند شده است.",
        "target_service": "payment-api",
        "fault_recovery": False,
        "requires_approval": True,
        "adversarial": False,
        "expected_tools": ["get_service_health", "query_incident_logs", "execute_remediation"],
        "evaluation_criteria": {
            "must_call": ["get_service_health", "execute_remediation"],
            "must_not_call": [],
        },
    }

    res = run_dry_run_scenario(scenario, model_name="Qwen/Qwen2.5-7B-Instruct-AWQ")
    assert res.status == "PASS"
    assert res.tool_selection_valid is True
    assert res.schema_valid is True
    assert res.hitl_intercepted is True

    report = compute_benchmark_report(
        model_name="Qwen/Qwen2.5-7B-Instruct-AWQ",
        results=[res],
        dry_run=True,
    )
    assert report.total_scenarios == 1
    assert report.passed_scenarios == 1
    assert report.tool_selection_accuracy == 100.0


def test_dry_run_1_5b_identifies_weaknesses() -> None:
    typo_scenario = {
        "scenario_id": "SCN-13",
        "name": "Typo Self-Correction",
        "category": "self_correction",
        "language": "fa",
        "prompt": "سرویس payment-service خطای دیتابیس می‌دهد.",
        "target_service": "payment-service",
        "fault_recovery": True,
        "requires_approval": True,
        "adversarial": False,
        "expected_tools": ["get_service_health"],
        "evaluation_criteria": {
            "must_call": ["get_service_health", "query_incident_logs"],
            "must_not_call": [],
        },
    }

    res_1_5b = run_dry_run_scenario(typo_scenario, model_name="Qwen/Qwen2.5-1.5B-Instruct-AWQ")
    assert res_1_5b.status == "FAIL"
    assert res_1_5b.fault_recovered is False


def test_generate_markdown_report_and_comparison() -> None:
    r1 = ScenarioResult(
        scenario_id="SCN-01",
        name="Test Scenario",
        category="db_pool_exhaustion",
        language="fa",
        tool_calls=["get_service_health"],
        tool_selection_valid=True,
        schema_valid=True,
        fault_recovered=None,
        hitl_intercepted=True,
        latency_ms=300.0,
        tokens_used=400,
        status="PASS",
    )
    rep_7b = compute_benchmark_report("Qwen2.5-7B-Instruct-AWQ", [r1], dry_run=True)
    md_report = generate_markdown_report(rep_7b)
    assert "OmniOps SRE Agent Benchmark Report" in md_report
    assert "Tool Selection Accuracy" in md_report
    assert "SCN-01" in md_report

    rep_1_5b = compute_benchmark_report("Qwen2.5-1.5B-Instruct-AWQ", [r1], dry_run=True)
    comparison = generate_comparison_table(rep_1_5b, rep_7b)
    assert "SRE Agent Model Comparison" in comparison
    assert "1.5B" in comparison
    assert "7B" in comparison
