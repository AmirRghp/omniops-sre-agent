"""Unit tests verifying the integrity and schema of agent evaluation scenarios."""

import json
from pathlib import Path

DATA_FILE = Path("data/agent_eval_scenarios.json")

VALID_SERVICES = {
    "payment-api",
    "auth-service",
    "postgres-primary",
    "redis-cache",
    "nginx-ingress",
}

VALID_ACTION_TYPES = {
    "restart_service",
    "scale_replicas",
    "flush_redis_cache",
    "increase_db_pool",
}

VALID_TOOLS = {
    "search_runbooks",
    "query_incident_logs",
    "get_service_health",
    "execute_remediation",
}

VALID_CATEGORIES = {
    "db_pool_exhaustion",
    "redis_oom",
    "cpu_throttling",
    "self_correction",
    "healthy_check",
    "adversarial_injection",
}


def test_eval_scenarios_file_exists() -> None:
    assert DATA_FILE.exists(), f"Evaluation scenarios file not found at {DATA_FILE}"


def test_eval_scenarios_count_and_uniqueness() -> None:
    content = DATA_FILE.read_text(encoding="utf-8")
    scenarios = json.loads(content)

    assert isinstance(scenarios, list)
    assert len(scenarios) == 25, f"Expected 25 scenarios, but found {len(scenarios)}"

    scenario_ids = [s["scenario_id"] for s in scenarios]
    assert len(scenario_ids) == len(set(scenario_ids)), "Scenario IDs must be unique"
    for i in range(1, 26):
        expected_id = f"SCN-{i:02d}"
        assert expected_id in scenario_ids, f"Missing scenario ID {expected_id}"


def test_eval_scenarios_schema_and_types() -> None:
    scenarios = json.loads(DATA_FILE.read_text(encoding="utf-8"))

    required_keys = {
        "scenario_id",
        "name",
        "category",
        "language",
        "prompt",
        "target_service",
        "fault_recovery",
        "requires_approval",
        "adversarial",
        "expected_tools",
        "expected_remediation",
        "evaluation_criteria",
    }

    for scenario in scenarios:
        sid = scenario.get("scenario_id", "UNKNOWN")
        assert required_keys.issubset(scenario.keys()), f"Missing keys in {sid}"

        assert scenario["category"] in VALID_CATEGORIES, f"Invalid category in {sid}"
        assert scenario["language"] in {"fa", "en"}, f"Invalid language in {sid}"
        assert isinstance(scenario["prompt"], str) and scenario["prompt"].strip()
        assert isinstance(scenario["fault_recovery"], bool)
        assert isinstance(scenario["requires_approval"], bool)
        assert isinstance(scenario["adversarial"], bool)
        assert isinstance(scenario["expected_tools"], list)
        assert isinstance(scenario["evaluation_criteria"], dict)

        for tool in scenario["expected_tools"]:
            assert tool in VALID_TOOLS, f"Invalid expected tool '{tool}' in {sid}"

        target = scenario["target_service"]
        if target is not None and not scenario["fault_recovery"]:
            assert target in VALID_SERVICES, f"Invalid service '{target}' in non-fault {sid}"

        remediation = scenario["expected_remediation"]
        if remediation is not None:
            assert isinstance(remediation, dict)
            assert remediation.get("action_type") in VALID_ACTION_TYPES, (
                f"Invalid action_type in {sid}"
            )
            assert remediation.get("service_name") in VALID_SERVICES, (
                f"Invalid remediation service_name in {sid}"
            )


def test_eval_scenarios_bilingual_balance() -> None:
    scenarios = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    fa_count = sum(1 for s in scenarios if s["language"] == "fa")
    en_count = sum(1 for s in scenarios if s["language"] == "en")

    assert fa_count >= 10, f"Expected at least 10 Persian scenarios, got {fa_count}"
    assert en_count >= 10, f"Expected at least 10 English scenarios, got {en_count}"
    assert fa_count + en_count == 25


def test_eval_scenarios_category_coverage() -> None:
    scenarios = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    categories = {s["category"] for s in scenarios}
    assert categories == VALID_CATEGORIES, f"Missing categories: {VALID_CATEGORIES - categories}"
