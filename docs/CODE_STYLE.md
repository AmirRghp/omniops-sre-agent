# Code Style & Engineering Standards (CODE_STYLE.md)

## 1. General Principles
- **Protocol-First Design:** MCP tools must be pure, stateless, async functions with strict Pydantic V2 input/output models.
- **Structured Errors Over Raw Exceptions:** Inside MCP tools, catch domain errors (like unknown service names or invalid parameter bounds) and return structured JSON dicts (`{"status": "error", "error_code": ..., "valid_options": ...}`) so the LLM can reason and self-correct.
- **Strict Type Safety:** 100% type annotations across all functions. `mypy --strict` must pass with zero warnings.
- **Async Everywhere:** Database queries (`asyncpg`), HTTP calls (`httpx.AsyncClient`), and LangGraph execution (`ainvoke` / `astream_events`) must be non-blocking.

---

## 2. Naming Conventions
- **MCP Tool Names:** `snake_case` verbs (`search_runbooks`, `query_incident_logs`, `get_service_health`, `execute_remediation`).
- **Classes & Models:** `PascalCase` (`IncidentState`, `RemediationRequest`, `RunbookCircuitBreaker`).
- **Constants:** `UPPER_SNAKE_CASE` (`MAX_AGENT_STEPS`, `DEFAULT_VLLM_URL`).

---

## 3. MCP Tool Implementation Pattern
Every tool in `src/mcp_server/tools.py` must follow this exact defensive pattern:
1. Validate inputs via Pydantic V2 schema.
2. Check preconditions against PostgreSQL.
3. Return a deterministic Pydantic response serialized via `.model_dump()`.
4. Never leak raw Python tracebacks to the LLM context window.

---

## 4. Formatting & Quality Gates
- **Formatter & Linter:** `ruff check src tests evals` and `ruff format --check src tests evals` (Line length: 100).
- **Static Type Checker:** `mypy src`
- **Test Runner:** `pytest -v`
