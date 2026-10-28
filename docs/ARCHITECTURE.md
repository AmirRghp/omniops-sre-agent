# System Architecture (ARCHITECTURE.md)

## 1. System Overview
OmniOps SRE Agent is a modular, production-grade autonomous incident response system built around two decoupled pillars:
1. **The Standardized MCP Server (`src/mcp_server/`):** Exposes infrastructure diagnostics, runbook search, and idempotent remediation tools over the Model Context Protocol (Stdio and HTTP/SSE).
2. **The Durable LangGraph Agent (`src/agent/`):** A stateful ReAct & Human-in-the-Loop orchestration graph backed by PostgreSQL checkpointing and powered by a local vLLM inference server (`Qwen2.5-Instruct-AWQ`).

---

## 2. Architecture Pattern
- **Pattern:** Decoupled Protocol-Driven Architecture (MCP Client-Server + Clean Architecture + Event-Driven State Machine).
- **Why this pattern?**
  - **Protocol Decoupling:** Because tools live behind an MCP boundary, the exact same tool server powers our LangGraph web application, CLI evaluation runner, Claude Desktop, and Cursor IDE.
  - **Durable Execution:** Using `AsyncPostgresSaver` in LangGraph allows the agent to pause indefinitely at a human approval gate without holding open threads or losing memory on container restarts.

---

## 3. Technology Stack & 16GB VRAM Budget Allocation
- **Local LLM Serving:** **vLLM** (`OpenAI-Compatible API` with PagedAttention, Continuous Batching, and Prefix Caching).
- **Supported Models (Configurable via `.env`):**
  - Primary Production Model: `Qwen/Qwen2.5-7B-Instruct-AWQ` (~5.2 GB VRAM weights + ~2.5 GB KV Cache at `--gpu-memory-utilization 0.60`).
  - Lightweight Comparison Model: `Qwen/Qwen2.5-1.5B-Instruct-AWQ` (~1.4 GB VRAM).
  - *VRAM Coexistence:* Even if Project 1 (`OmniDoc RAG` with BGE-M3 + Reranker ~2.2 GB VRAM) runs simultaneously on the same machine, total VRAM stays around **9.9 GB / 16.0 GB**, leaving >6 GB safety headroom.
- **Agent Orchestration:** **LangGraph** (`StateGraph`, `AsyncPostgresSaver`, `interrupt_before`).
- **Tool Protocol:** **Official Python `mcp` SDK (`FastMCP`)** supporting both `stdio` and `sse` transports.
- **Database:** **PostgreSQL 16** (`asyncpg` + `SQLAlchemy 2.0 Async` + `langgraph-checkpoint-postgres`).
- **Backend API:** **FastAPI** (Async REST + SSE streaming endpoints).
- **Frontend UI:** **Chainlit** (Step visualization + interactive `cl.Action` approval buttons).
- **Observability:** **Langfuse** (Self-hosted trace logging of tool calls, latencies, and token budgets).

---

## 4. Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    External MCP Clients (Optional)                      │
│               (Cursor IDE / Claude Desktop / MCP Inspector)             │
└───────────────────────────────────┬─────────────────────────────────────┘
                                    │ (Stdio / SSE MCP Protocol)
┌───────────────────────┐           ▼           ┌─────────────────────────┐
│    Chainlit Web UI    │   ┌───────────────┐   │  Project 1: OmniDoc RAG │
│ (Incident Console &   │   │  OmniOps MCP  │──►│   (Port 8080 Live API)  │
│  Approve/Reject Gate) │   │    Server     │   └────────────┬────────────┘
└───────────▲───────────┘   │               │                │ (Circuit Breaker)
            │ SSE / Actions │  4 Narrow     │   ┌────────────▼────────────┐
┌───────────▼───────────┐   │  Typed Tools  │──►│ Local Fallback Runbooks │
│  FastAPI Backend API  │   └───────▲───────┘   │ (data/runbooks.json)    │
└───────────▲───────────┘           │           └─────────────────────────┘
            │                       │ (Tool Calls & Structured JSON)
┌───────────▼───────────────────────┴─────────────────────────────────────┐
│                     LangGraph Durable State Machine                     │
│                                                                         │
│  [START] ──► [agent_reasoning_node] ◄──► [read_only_tools_node]         │
│                       │                                                 │
│          (Calls execute_remediation)                                    │
│                       ▼                                                 │
│         ⏸️ [HUMAN APPROVAL INTERRUPT GATE]                              │
│                       │                                                 │
│            ┌──────────┴──────────┐                                      │
│        Approved               Rejected                                  │
│            ▼                     ▼                                      │
│  [remediation_node]     [rejection_handler]                             │
│  (Idempotent Write)              │                                      │
│            └──────────┬──────────┘                                      │
│                       ▼                                                 │
│             [agent_reasoning_node] ──► [END]                            │
└───────────────────────┬─────────────────────────────────────────────────┘
                        │
        ┌───────────────┴───────────────┐
        ▼                               ▼
┌───────────────────────┐       ┌───────────────────────┐
│     PostgreSQL 16     │       │   vLLM Local Server   │
│ - Operational Tables  │       │ Qwen2.5-7B / 1.5B AWQ │
│ - Idempotency Ledger  │       │ (Port 8000)           │
│ - LangGraph Checkpts  │       └───────────────────────┘
└───────────────────────┘
```

---

## 5. Project Structure

```text
omniops-sre-agent/
├── .github/
│   └── workflows/
│       ├── ci.yml                       # Ruff, Mypy, Pytest (No-LLM unit & integration tests)
│       └── agent-evals.yml              # Deterministic tool-calling benchmark workflow
├── configs/
│   ├── config.yaml                      # Step ceilings, timeouts, circuit breaker settings
│   └── prompts.yaml                     # SRE system prompt, safety rules, formatting rules
├── data/
│   ├── fallback_runbooks.json           # Self-contained fallback runbooks when Project 1 is offline
│   ├── seed_incidents.sql               # Realistic operational telemetry, logs, and services
│   └── agent_eval_scenarios.json        # 25 multi-step SRE evaluation scenarios
├── docs/                                # Complete Vibe Coding Blueprint Suite
│   ├── PRD.md
│   ├── DESIGN_SYSTEM.md
│   ├── UX_FLOWS.md
│   ├── ARCHITECTURE.md
│   ├── DATABASE.md
│   ├── API.md
│   ├── SECURITY.md
│   ├── CODE_STYLE.md
│   ├── TESTING.md
│   └── PLAN.md
├── AGENTS.md                            # AI Agent operational guidelines & source of truth
├── CLAUDE.md                            # Entrypoint instruction file for Claude
├── GEMINI.md                            # Entrypoint instruction file for Gemini
├── evals/
│   ├── __init__.py
│   ├── run_agent_benchmark.py           # Evaluates 1.5B vs 7B on 25 scenarios
│   ├── fault_injection.py               # Simulates tool failures to measure recovery rate
│   └── results/                         # Generated Markdown & JSON benchmark reports
├── src/
│   ├── __init__.py
│   ├── common/
│   │   ├── config.py                    # Pydantic V2 BaseSettings
│   │   ├── exceptions.py                # Domain & tool error hierarchy
│   │   └── logger.py                    # Structured JSON logger with trace_id
│   ├── db/
│   │   ├── models.py                    # SQLAlchemy 2.0 models (Services, Logs, Remediations)
│   │   ├── session.py                   # Async engine & session maker
│   │   └── seed.py                      # Idempotent database seeder
│   ├── mcp_server/
│   │   ├── __init__.py
│   │   ├── schemas.py                   # Strict Pydantic input/output schemas for 4 tools
│   │   ├── runbook_client.py            # Circuit breaker client (Project 1 API + Local Fallback)
│   │   ├── tools.py                     # Core logic of the 4 SRE tools
│   │   └── server.py                    # FastMCP entrypoint (Stdio & SSE)
│   ├── agent/
│   │   ├── state.py                     # IncidentState TypedDict (messages, steps, pending_action)
│   │   ├── nodes.py                     # Planner, ReadToolNode, ApprovalGate, WriteToolNode
│   │   └── graph.py                     # LangGraph builder with AsyncPostgresSaver
│   └── api/
│       ├── routes.py                    # FastAPI endpoints (/incident/stream, /incident/approve)
│       └── schemas.py                   # API Request/Response contracts
├── tests/
│   ├── unit/
│   │   ├── test_mcp_tools.py            # Direct tool tests (Zero LLM dependency)
│   │   ├── test_idempotency.py          # Duplicate key prevention tests
│   │   └── test_circuit_breaker.py      # Live vs Fallback runbook switching tests
│   └── integration/
│       ├── test_graph_interrupt.py      # Verifies HITL pause and resume mechanics
│       └── test_api_endpoints.py        # FastAPI integration tests
├── app.py                               # Chainlit Incident Console UI
├── main.py                              # FastAPI application entrypoint
├── docker-compose.yml                   # PostgreSQL 16, Langfuse, App Init
├── Dockerfile
├── Makefile
├── pyproject.toml
├── requirements.txt
└── README.md
```

---

## 6. Key Architecture Decision Records (ADRs)

### ADR-001: Four Narrow MCP Tools Instead of a Generic "InfraTool"
- **Context:** Models frequently hallucinate combinations of parameters when given a single monolithic tool like `manage_infra(mode="logs" | "metrics" | "restart", ...)`.
- **Decision:** Split capabilities into 4 distinct, narrow tools (`search_runbooks`, `query_incident_logs`, `get_service_health`, `execute_remediation`).
- **Consequence:** Drastically reduces schema confusion, enables separating Read-Only tools from Write-Gated tools in LangGraph routing, and makes unit testing trivial.

### ADR-002: Circuit Breaker Pattern for Project 1 (`OmniDoc RAG`) Integration
- **Context:** Project 2 should showcase ecosystem integration with Project 1, but forcing reviewers to run two separate repositories simultaneously increases friction.
- **Decision:** Implement an automatic Circuit Breaker in `runbook_client.py` with a 1.5-second timeout. If `http://localhost:8080` is reachable, query Project 1; otherwise, transparently query `data/fallback_runbooks.json`.
- **Consequence:** Zero single-point-of-failure; works out-of-the-box standalone AND in full ecosystem mode.

### ADR-003: Hard Separating Read-Only vs. Consequential Tool Nodes in LangGraph
- **Context:** Read-only diagnostic tools (`get_service_health`, `query_incident_logs`, `search_runbooks`) should execute autonomously for speed, whereas `execute_remediation` modifies infrastructure state.
- **Decision:** Route read-only tool calls to `read_tools_node` (auto-execution) and route `execute_remediation` calls to `remediation_node` configured with `interrupt_before=["remediation_node"]`.
- **Consequence:** 100% deterministic enforcement of Human-in-the-Loop safety at the graph architecture level, not relying on prompt obedience.
