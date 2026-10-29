# Step-by-Step Implementation Plan (PLAN.md)

## Overview
This plan breaks the implementation of **OmniOps SRE Agent** into **9 Phases** and **24 Atomic Tasks**. Execute each task sequentially, verifying its test command before proceeding to the next.

---

## Phase 1: Repository Scaffolding & Configuration
### Task 1.1: Project Skeleton & Dependency Setup
- **Reference Docs:** `docs/ARCHITECTURE.md`, `docs/CODE_STYLE.md`
- **Target Files:** `pyproject.toml`, `requirements.txt`, `.env.example`, `.gitignore`, `Makefile`
- **Implementation Details:**
  - Create directory tree (`src/common`, `src/db`, `src/mcp_server`, `src/agent`, `src/api`, `tests/unit`, `tests/integration`, `evals`, `data`, `configs`).
  - Populate `requirements.txt` (`fastapi`, `uvicorn`, `pydantic>=2.9`, `pydantic-settings`, `sqlalchemy[asyncio]>=2.0`, `asyncpg`, `langgraph`, `langgraph-checkpoint-postgres`, `psycopg[binary,pool]`, `mcp`, `openai`, `httpx`, `chainlit`, `langfuse`, `pytest`, `pytest-asyncio`, `ruff`, `mypy`).
- **Verification:** `pip install -r requirements.txt && ruff --version`

### Task 1.2: Core Settings, Logger & Custom Exceptions
- **Reference Docs:** `docs/CODE_STYLE.md`, `docs/SECURITY.md`
- **Target Files:** `src/common/config.py`, `src/common/logger.py`, `src/common/exceptions.py`, `configs/config.yaml`
- **Implementation Details:**
  - Implement `Settings(BaseSettings)` loading `LLM_BASE_URL`, `LLM_MODEL_NAME` (default `Qwen/Qwen2.5-7B-Instruct-AWQ`), `DATABASE_URL`, `OMNIDOC_RAG_URL` (`http://localhost:8080/api/v1/query`), `MAX_AGENT_STEPS=6`, `API_KEY`.
- **Verification:** `pytest tests/unit/test_config.py`

---

## Phase 2: Database Layer & Realistic Incident Seed Data
### Task 2.1: Docker Compose Infrastructure (PostgreSQL 16 & Langfuse)
- **Reference Docs:** `docs/ARCHITECTURE.md`, `docs/DATABASE.md`
- **Target Files:** `docker-compose.yml`
- **Implementation Details:**
  - Configure `postgres:16-alpine` on port `5432` (with healthcheck) and `langfuse` on port `3000`.
- **Verification:** `docker compose up -d postgres && docker compose ps`

### Task 2.2: SQLAlchemy 2.0 Async Models & Session Manager
- **Reference Docs:** `docs/DATABASE.md`
- **Target Files:** `src/db/models.py`, `src/db/session.py`
- **Implementation Details:**
  - Define `InfraService`, `IncidentLog`, and `RemediationExecution` ORM models matching exact SQL constraints in `docs/DATABASE.md`.
- **Verification:** `mypy src/db`

### Task 2.3: Operational Seeder & Local Fallback Runbooks
- **Reference Docs:** `docs/DATABASE.md`, `docs/UX_FLOWS.md`
- **Target Files:** `src/db/seed.py`, `data/fallback_runbooks.json`
- **Implementation Details:**
  - Write idempotent `seed_database()` populating the 5 microservices (`payment-api`, `redis-cache`, `auth-service`, `postgres-primary`, `nginx-ingress`) and realistic error logs (`ERR_DB_POOL_EXHAUSTED`, `ERR_REDIS_OOM_EVICTION`, `WARN_HIGH_CPU_THROTTLING`, `HTTP_502_BAD_GATEWAY`).
  - Create `data/fallback_runbooks.json` with 10 detailed bilingual SRE troubleshooting runbooks (`RB-101` through `RB-110`).
- **Verification:** `python -m src.db.seed`

---

## Phase 3: Standardized MCP Server & 4 Narrow Tools
### Task 3.1: Strict Pydantic Schemas for MCP Tools
- **Reference Docs:** `docs/API.md`, `docs/CODE_STYLE.md`
- **Target Files:** `src/mcp_server/schemas.py`, `tests/unit/test_schemas.py`
- **Implementation Details:**
  - Define input and output Pydantic V2 models for `search_runbooks`, `query_incident_logs`, `get_service_health`, and `execute_remediation`.
- **Verification:** `pytest tests/unit/test_schemas.py -v`

### Task 3.2: Circuit Breaker Runbook Client (Project 1 Live + Local Fallback)
- **Reference Docs:** `docs/ARCHITECTURE.md` (ADR-002), `docs/UX_FLOWS.md` (Flow 4)
- **Target Files:** `src/mcp_server/runbook_client.py`, `tests/unit/test_circuit_breaker.py`
- **Implementation Details:**
  - Implement `RunbookClient.search(query, category)`. Attempt async POST to `OMNIDOC_RAG_URL` with a `1.5s` timeout. If reachable, return Project 1 citations with `source_mode="LIVE_OMNIDOC_RAG"`. On connection error or timeout, score and return top matches from `data/fallback_runbooks.json` with `source_mode="LOCAL_FALLBACK"`.
- **Verification:** `pytest tests/unit/test_circuit_breaker.py -v`

### Task 3.3: Read-Only Diagnostic Tools (`get_service_health` & `query_incident_logs`)
- **Reference Docs:** `docs/API.md`, `docs/SECURITY.md`
- **Target Files:** `src/mcp_server/tools.py`, `tests/unit/test_mcp_tools.py`
- **Implementation Details:**
  - Implement both async tools. If `service_name` is not found in `infra_services`, return the structured error dictionary listing `valid_services` instead of raising an exception. Wrap log messages in `<untrusted_log_data>` tags.
- **Verification:** `pytest tests/unit/test_mcp_tools.py -v`

### Task 3.4: Idempotent Write Tool (`execute_remediation`)
- **Reference Docs:** `docs/DATABASE.md`, `docs/SECURITY.md`
- **Target Files:** `src/mcp_server/tools.py`, `tests/unit/test_idempotency.py`
- **Implementation Details:**
  - Check `remediation_executions` for `idempotency_key`. If already executed, return cached result with `idempotent_replay=True`. Otherwise, apply state change to `infra_services` (e.g., update `db_pool_size=200` and set `status='HEALTHY'`, `p95_latency_ms=140`), insert audit record, and commit transaction.
- **Verification:** `pytest tests/unit/test_idempotency.py -v`

### Task 3.5: FastMCP Server Entrypoint (Stdio & SSE Transports)
- **Reference Docs:** `docs/PRD.md`, `docs/API.md`
- **Target Files:** `src/mcp_server/server.py`
- **Implementation Details:**
  - Register all 4 tools with `FastMCP("omniops-sre-mcp")`. Support running via `python -m src.mcp_server.server --transport stdio` (for Claude Desktop / Cursor) and `--transport sse`.
- **Verification:** `python -m src.mcp_server.server --help`

---

## Phase 4: LangGraph Durable State Machine & HITL Gate
### Task 4.1: Agent State & System Prompts
- **Reference Docs:** `docs/ARCHITECTURE.md`, `docs/SECURITY.md`
- **Target Files:** `src/agent/state.py`, `configs/prompts.yaml`
- **Implementation Details:**
  - Define `IncidentState(TypedDict)` with `messages`, `step_count`, `tokens_used`, `pending_remediation`, `approval_status`, and `fallback_used`.
  - Craft bilingual SRE system prompt instructing the model to diagnose before remediating and never invent service names.
- **Verification:** `mypy src/agent/state.py`

### Task 4.2: Reasoning, Read-Tool, and Step-Ceiling Nodes
- **Reference Docs:** `docs/ARCHITECTURE.md`, `docs/UX_FLOWS.md`
- **Target Files:** `src/agent/nodes.py`
- **Implementation Details:**
  - Implement `agent_reasoning_node` calling vLLM (`AsyncOpenAI` with tool definitions), `read_tools_node` executing read-only tools concurrently, and `force_terminate_node` when `step_count >= MAX_AGENT_STEPS`.
- **Verification:** `mypy src/agent/nodes.py`

### Task 4.3: Human-in-the-Loop Interrupt & Remediation Node
- **Reference Docs:** `docs/ARCHITECTURE.md` (ADR-003), `docs/UX_FLOWS.md` (Flows 1 & 2)
- **Target Files:** `src/agent/graph.py`, `tests/integration/test_graph_interrupt.py`
- **Implementation Details:**
  - Build `StateGraph(IncidentState)`. Route tool calls: if tool name is in `{"search_runbooks", "query_incident_logs", "get_service_health"}`, route to `read_tools_node`; if tool name is `"execute_remediation"`, route to `remediation_node`.
  - Compile graph with `checkpointer=postgres_saver` and `interrupt_before=["remediation_node"]`.
  - Implement `resume_with_approval(thread_id, decision, operator_id, comment)` to either execute the remediation or inject a rejection `ToolMessage`.
- **Verification:** `pytest tests/integration/test_graph_interrupt.py -v`

---

## Phase 5: FastAPI Backend & SSE Streaming
### Task 5.1: API Schemas & Endpoints (`/incident/stream`, `/incident/approve`, `/infra/reset`)
- **Reference Docs:** `docs/API.md`, `docs/SECURITY.md`
- **Target Files:** `src/api/schemas.py`, `src/api/routes.py`, `main.py`, `tests/integration/test_api_endpoints.py`
- **Implementation Details:**
  - Implement SSE streaming generator yielding structured events (`tool_call`, `tool_result`, `approval_required`, `token`, `done`).
  - Implement `/api/v1/incident/approve` to resume interrupted threads.
- **Verification:** `pytest tests/integration/test_api_endpoints.py -v`

---

## Phase 6: Chainlit Interactive SRE Console
### Task 6.1: Real-Time Tool Accordions & Interactive Approval Card
- **Reference Docs:** `docs/DESIGN_SYSTEM.md`, `docs/UX_FLOWS.md`
- **Target Files:** `app.py`, `public/custom.css`
- **Implementation Details:**
  - Render each MCP tool call inside a `cl.Step` showing JSON arguments, execution duration, and `[Mode: Live OmniDoc RAG | Local Fallback]` badge.
  - When the graph pauses at `interrupt_before=["remediation_node"]`, display a highlighted card with `cl.Action(name="approve_action", ...)` and `cl.Action(name="reject_action", ...)`.
- **Verification:** Manual UI check via `chainlit run app.py`

---

## Phase 7: Quantitative Agent Evaluation & Model Comparison (`1.5B` vs. `7B`)
### Task 7.1: Curate 25 Multi-Step SRE Evaluation Scenarios
- **Reference Docs:** `docs/TESTING.md`
- **Target Files:** `data/agent_eval_scenarios.json`
- **Implementation Details:**
  - Create 25 diverse bilingual test scenarios covering: DB pool exhaustion, Redis OOM, CPU throttling, typoed service names requiring self-correction, healthy service checks, and adversarial log injection prompts.

### Task 7.2: Agent Benchmark Runner & Fault Injection Suite
- **Reference Docs:** `docs/PRD.md`, `docs/TESTING.md`
- **Target Files:** `evals/run_agent_benchmark.py`, `evals/fault_injection.py`
- **Implementation Details:**
  - Measure Tool Selection Accuracy, Argument Schema Validity, Fault Recovery Rate, HITL Gate Interception, and P95 Latency.
  - Support CLI flag `--model` to run benchmarks on both `Qwen/Qwen2.5-1.5B-Instruct-AWQ` and `Qwen/Qwen2.5-7B-Instruct-AWQ` and output a comparative Markdown table.
- **Verification:** `python -m evals.run_agent_benchmark --dry-run`

---

## Phase 8: Packaging, CI/CD & Portfolio Polish
### Task 8.1: One-Command Startup (`Makefile` / `init` container) & GitHub Actions
- **Reference Docs:** `docs/ARCHITECTURE.md`, `docs/TESTING.md`
- **Target Files:** `Makefile`, `.github/workflows/ci.yml`, `README.md`
- **Implementation Details:**
  - Configure automatic DB migration & seeding on startup so `docker compose up -d` prepares the entire environment in one command.
  - Write comprehensive `README.md` including architecture diagram, MCP client configuration for Cursor/Claude Desktop, `1.5B` vs `7B` benchmark table, and `Limitations & Failure Modes`.
- **Verification:** `ruff check . && mypy src && pytest`
