"""Circuit breaker client for runbook queries.

Integrates with Project 1 (OmniDoc RAG) via an automated circuit breaker
and provides transparent local fallback to data/fallback_runbooks.json.
"""

import json
import re
import time
from enum import StrEnum
from pathlib import Path
from typing import Any

import httpx

from src.common.config import get_settings, load_yaml_config
from src.common.logger import setup_logger
from src.mcp_server.schemas import RunbookResult, SearchRunbooksOutput

logger = setup_logger("runbook_client")


class CircuitBreakerState(StrEnum):
    """Operational states of the RunbookCircuitBreaker."""

    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class RunbookCircuitBreaker:
    """Circuit breaker protecting external OmniDoc RAG calls.

    Transitions:
    - CLOSED -> OPEN: When failure_count >= failure_threshold
    - OPEN -> HALF_OPEN: When recovery_timeout_seconds has elapsed
    - HALF_OPEN -> CLOSED: On successful request probe
    - HALF_OPEN -> OPEN: On probe failure
    """

    def __init__(
        self,
        failure_threshold: int = 3,
        recovery_timeout_seconds: float = 30.0,
        request_timeout_seconds: float = 1.5,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_timeout_seconds = recovery_timeout_seconds
        self.request_timeout_seconds = request_timeout_seconds
        self.state: CircuitBreakerState = CircuitBreakerState.CLOSED
        self.failure_count = 0
        self.last_failure_time: float = 0.0

    def can_execute(self) -> bool:
        """Check whether an outbound request is permitted."""
        if self.state == CircuitBreakerState.CLOSED:
            return True

        if self.state == CircuitBreakerState.OPEN:
            now = time.monotonic()
            if now - self.last_failure_time >= self.recovery_timeout_seconds:
                self.state = CircuitBreakerState.HALF_OPEN
                return True
            return False

        # In HALF_OPEN, allow single probe attempt
        return True

    def record_success(self) -> None:
        """Register a successful request and reset breaker to CLOSED."""
        self.state = CircuitBreakerState.CLOSED
        self.failure_count = 0

    def record_failure(self) -> None:
        """Register a failed request, updating state if threshold exceeded."""
        self.failure_count += 1
        self.last_failure_time = time.monotonic()

        if (
            self.failure_count >= self.failure_threshold
            or self.state == CircuitBreakerState.HALF_OPEN
        ):
            self.state = CircuitBreakerState.OPEN


class RunbookClient:
    """Client for retrieving troubleshooting runbooks with automated fallback."""

    def __init__(
        self,
        rag_url: str | None = None,
        fallback_path: Path | str | None = None,
        circuit_breaker: RunbookCircuitBreaker | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        settings = get_settings()
        self.rag_url = rag_url or settings.OMNIDOC_RAG_URL
        self.fallback_path = Path(fallback_path or settings.FALLBACK_RUNBOOKS_PATH)

        if circuit_breaker is None:
            try:
                yaml_cfg = load_yaml_config()
                cb_cfg = yaml_cfg.get("circuit_breaker", {})
                self.circuit_breaker = RunbookCircuitBreaker(
                    failure_threshold=cb_cfg.get("failure_threshold", 3),
                    recovery_timeout_seconds=cb_cfg.get("recovery_timeout_seconds", 30.0),
                    request_timeout_seconds=cb_cfg.get("request_timeout_seconds", 1.5),
                )
            except Exception:
                self.circuit_breaker = RunbookCircuitBreaker()
        else:
            self.circuit_breaker = circuit_breaker

        self._client = client
        self._fallback_cache: list[dict[str, Any]] | None = None

    def _load_fallback_runbooks(self) -> list[dict[str, Any]]:
        """Load and cache fallback runbooks dataset from disk."""
        if self._fallback_cache is not None:
            return self._fallback_cache

        if not self.fallback_path.exists():
            logger.error("Fallback runbooks file not found at %s", self.fallback_path)
            return []

        try:
            with open(self.fallback_path, encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    self._fallback_cache = data
                    return self._fallback_cache
                logger.error("Fallback runbooks root is not a list in %s", self.fallback_path)
                return []
        except Exception as exc:
            logger.error("Failed to load fallback runbooks from %s: %s", self.fallback_path, exc)
            return []

    async def search(self, query: str, category: str | None = None) -> SearchRunbooksOutput:
        """Search runbooks through OmniDoc RAG or transparent local fallback."""
        if self.circuit_breaker.can_execute():
            try:
                results = await self._query_live_rag(query, category)
                self.circuit_breaker.record_success()
                return SearchRunbooksOutput(
                    status="success",
                    source_mode="LIVE_OMNIDOC_RAG",
                    results=results,
                )
            except Exception as exc:
                self.circuit_breaker.record_failure()
                logger.warning(
                    "OmniDoc RAG call failed (%s). Circuit breaker: state=%s, failures=%d. "
                    "Falling back to local runbooks.",
                    str(exc),
                    self.circuit_breaker.state.value,
                    self.circuit_breaker.failure_count,
                )

        # Fallback to local store
        fallback_results = self.search_fallback(query=query, category=category)
        return SearchRunbooksOutput(
            status="success",
            source_mode="LOCAL_FALLBACK",
            results=fallback_results,
        )

    async def _query_live_rag(self, query: str, category: str | None = None) -> list[RunbookResult]:
        """Perform outbound HTTP POST to OmniDoc RAG with timeout."""
        payload: dict[str, Any] = {"query": query}
        if category:
            payload["category"] = category

        timeout = self.circuit_breaker.request_timeout_seconds
        headers: dict[str, str] = {}
        settings = get_settings()
        if settings.API_KEY:
            headers["Authorization"] = f"Bearer {settings.API_KEY}"

        if self._client:
            response = await self._client.post(
                self.rag_url, json=payload, headers=headers, timeout=timeout
            )
        else:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(self.rag_url, json=payload, headers=headers)

        response.raise_for_status()
        data = response.json()

        raw_results: list[dict[str, Any]] = []
        if isinstance(data, list):
            raw_results = data
        elif isinstance(data, dict):
            found = data.get("results") or data.get("citations")
            if isinstance(found, list):
                raw_results = found

        results: list[RunbookResult] = []
        for item in raw_results:
            rid = str(item.get("runbook_id") or "")
            if not rid or rid == "RB-UNKNOWN":
                fb = self.search_fallback(query=query, category=category, top_k=1)
                rid = fb[0].runbook_id if fb else str(item.get("source_file", "RB-UNKNOWN"))
            results.append(
                RunbookResult(
                    runbook_id=rid,
                    title=str(item.get("title") or item.get("section_heading", "Runbook")),
                    content=str(item.get("content") or item.get("snippet", "")),
                    relevance_score=max(0.0, min(1.0, float(item.get("relevance_score", 0.90)))),
                )
            )
        return results

    def search_fallback(
        self, query: str, category: str | None = None, top_k: int = 3
    ) -> list[RunbookResult]:
        """Score and return top matching runbooks from local dataset."""
        runbooks = self._load_fallback_runbooks()
        if not runbooks:
            return []

        query_clean = query.strip()
        query_lower = query_clean.lower()
        # Extract word/code tokens (support English alphanumeric, Persian characters, underscores)
        query_tokens = set(re.findall(r"[\w\u0600-\u06FF]+", query_lower))

        scored_runbooks: list[tuple[float, dict[str, Any]]] = []

        for rb in runbooks:
            # If category specified, enforce strict category filter
            if category and rb.get("category") != category:
                continue

            score = 0.0

            # 1. Exact Runbook ID match
            rb_id = str(rb.get("runbook_id", "")).lower()
            if rb_id and rb_id in query_lower:
                score += 0.85

            # 2. Error code matches (e.g. ERR_DB_POOL_EXHAUSTED)
            for err_code in rb.get("error_codes", []):
                err_lower = err_code.lower()
                if err_lower in query_lower:
                    score += 0.75
                    break
                # Partial token overlap in error codes
                err_tokens = set(err_lower.split("_"))
                overlap = query_tokens.intersection(err_tokens)
                if overlap:
                    score += 0.20 * (len(overlap) / len(err_tokens))

            # 3. Target service match (e.g. payment-api, redis-cache)
            for svc in rb.get("target_services", []):
                if svc.lower() in query_lower:
                    score += 0.15
                    break

            # 4. Text similarity / bilingual keywords
            title_text = f"{rb.get('title', '')} {rb.get('title_fa', '')}".lower()
            symptom_text = f"{rb.get('symptoms', '')} {rb.get('symptoms_fa', '')}".lower()
            content_text = str(rb.get("content", "")).lower()

            for token in query_tokens:
                if len(token) < 2:
                    continue
                if token in title_text:
                    score += 0.15
                elif token in symptom_text:
                    score += 0.10
                elif token in content_text:
                    score += 0.05

            if score > 0.05:
                normalized_score = min(0.99, max(0.10, score))
                scored_runbooks.append((normalized_score, rb))

        # Sort descending by score
        scored_runbooks.sort(key=lambda x: x[0], reverse=True)

        results: list[RunbookResult] = []
        for score, rb in scored_runbooks[:top_k]:
            results.append(
                RunbookResult(
                    runbook_id=rb.get("runbook_id", "RB-UNKNOWN"),
                    title=rb.get("title", "Runbook"),
                    content=rb.get("content", ""),
                    relevance_score=round(score, 2),
                )
            )

        return results
