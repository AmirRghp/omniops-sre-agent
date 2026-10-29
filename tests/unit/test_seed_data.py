"""Unit tests for fallback runbooks dataset integrity."""

import json
from pathlib import Path


def test_fallback_runbooks_file_exists() -> None:
    """Verify that data/fallback_runbooks.json exists and is valid JSON."""
    file_path = Path("data/fallback_runbooks.json")
    assert file_path.exists(), "fallback_runbooks.json not found in data/"

    with open(file_path, encoding="utf-8") as f:
        runbooks = json.load(f)

    assert isinstance(runbooks, list)
    assert len(runbooks) == 10, f"Expected 10 runbooks, found {len(runbooks)}"


def test_fallback_runbooks_schema_and_coverage() -> None:
    """Verify required fields, categories, error codes, and unique IDs."""
    with open("data/fallback_runbooks.json", encoding="utf-8") as f:
        runbooks = json.load(f)

    valid_categories = {"database", "caching", "networking", "containers", "general"}
    valid_actions = {
        "restart_service",
        "scale_replicas",
        "flush_redis_cache",
        "increase_db_pool",
    }

    seen_ids = set()
    found_error_codes = set()

    for rb in runbooks:
        # Check required fields
        assert "runbook_id" in rb
        assert "title" in rb
        assert "title_fa" in rb
        assert "category" in rb
        assert "target_services" in rb
        assert "error_codes" in rb
        assert "symptoms" in rb
        assert "content" in rb
        assert "recommended_action" in rb

        rb_id = rb["runbook_id"]
        assert rb_id.startswith("RB-")
        assert rb_id not in seen_ids, f"Duplicate runbook ID: {rb_id}"
        seen_ids.add(rb_id)

        # Check category and actions
        assert rb["category"] in valid_categories
        assert rb["recommended_action"]["action_type"] in valid_actions

        for code in rb["error_codes"]:
            found_error_codes.add(code)

    # Ensure all primary incident error codes are covered
    assert "ERR_DB_POOL_EXHAUSTED" in found_error_codes
    assert "ERR_REDIS_OOM_EVICTION" in found_error_codes
    assert "WARN_HIGH_CPU_THROTTLING" in found_error_codes
    assert "HTTP_502_BAD_GATEWAY" in found_error_codes
