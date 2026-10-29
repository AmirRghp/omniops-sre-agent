# OmniOps SRE Agent ⚡

> **Autonomous Incident Response & Model Context Protocol (MCP) Platform**
> *Project 2 of the AI Engineering Roadmap — Built for Autonomous Triage, Deterministic MCP Tooling, and Human-in-the-Loop Infrastructure Safety.*

[![CI Quality Gate](https://github.com/AmirRghp/omniops-sre-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/AmirRghp/omniops-sre-agent/actions/workflows/ci.yml)
[![Deterministic Benchmark](https://github.com/AmirRghp/omniops-sre-agent/actions/workflows/agent-evals.yml/badge.svg)](https://github.com/AmirRghp/omniops-sre-agent/actions/workflows/agent-evals.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastMCP](https://img.shields.io/badge/MCP-FastMCP%20SDK-purple.svg)](https://modelcontextprotocol.io/)
[![LangGraph](https://img.shields.io/badge/Orchestration-LangGraph%20AsyncPostgres-orange.svg)](https://langchain-ai.github.io/langgraph/)
[![vLLM Ready](https://img.shields.io/badge/Inference-vLLM%20AWQ-green.svg)](https://github.com/vllm-project/vllm)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## 1. System Overview

**OmniOps SRE Agent** is a production-hardened, bilingual (Persian & English) autonomous Site Reliability Engineering platform. It solves alert fatigue and triage delays by autonomously correlating live telemetry, querying structured incident logs, consulting technical runbooks, and executing remediation actions behind an immutable **Human-in-the-Loop (HITL)** approval gate.

### Key Architectural Pillars:
1. **Decoupled Protocol-Driven Architecture:** All capabilities live behind the official **Model Context Protocol (MCP)** via `FastMCP`. The exact same tool server powers the internal LangGraph agent, the Chainlit console, Cursor IDE, and Claude Desktop.
2. **Durable State Machine with PostgreSQL Checkpoints:** Built on LangGraph with `AsyncPostgresSaver`, enabling multi-turn investigations to pause indefinitely at human checkpoints without holding open socket connections or losing state on container restarts.
3. **Hard Human-in-the-Loop Safety Gate:** State-changing write actions (`execute_remediation`) are strictly gated by `interrupt_before=["remediation_node"]`. The LLM cannot execute an unapproved mutation regardless of prompt injection or runaway loops.
4. **Resilient Circuit Breaker (Standalone Guarantee):** Connects to Project 1 (`OmniDoc RAG`) on port `8080`. If Project 1 is offline, queries transparently fall back to built-in bilingual runbooks (`data/fallback_runbooks.json`) with zero downtime.
5. **16GB VRAM Discipline:** Optimized for local serving via vLLM with `Qwen/Qwen2.5-7B-Instruct-AWQ` (`--gpu-memory-utilization 0.60`), fitting alongside other ecosystem services with >6GB headroom.

---

## 2. Architecture Diagram

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
└───────────▲───────────┘   │ (FastMCP SDK) │                │ (Circuit Breaker)
            │ SSE / Actions │               │   ┌────────────▼────────────┐
┌───────────▼───────────┐   │  4 Narrow     │──►│ Local Fallback Runbooks │
│  FastAPI Backend API  │   │  Typed Tools  │   │ (data/fallback_...json) │
└───────────▲───────────┘   └───────▲───────┘   └─────────────────────────┘
            │                       │ (Structured Pydantic Payloads)
┌───────────▼───────────────────────┴─────────────────────────────────────┐
│                     LangGraph Durable State Machine                     │
│                                                                         │
│  [START] ──► [agent_reasoning_node] ◄──► [read_tools_node]             │
│                       │                                                 │
│          (Proposes execute_remediation)                                 │
│                       ▼                                                 │
│         ⏸️ [HUMAN APPROVAL INTERRUPT GATE]                              │
│         (interrupt_before=["remediation_node"])                         │
│                       │                                                 │
│            ┌──────────┴──────────┐                                      │
│        Approved               Rejected                                  │
│            ▼                     ▼                                      │
│  [remediation_node]     [rejection_handler]                             │
│  (Idempotent Write)     (Safe Manual Advice)                            │
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

## 3. Four Narrow MCP Tools

To prevent parameter hallucination common in monolithic tools, capabilities are divided into 4 narrow, strictly typed tools:

| MCP Tool Name | Access Mode | Description |
| :--- | :---: | :--- |
| `get_service_health(service_name)` | **Read-Only** | Queries real-time CPU, RAM, replica counts, connection pool, and status. |
| `query_incident_logs(service_name, severity, limit)` | **Read-Only** | Retrieves recent error/warning logs wrapped in `<untrusted_log_data>` tags. |
| `search_runbooks(query, category)` | **Read-Only** | Circuit-breaker search querying Project 1 RAG or local fallback runbooks. |
| `execute_remediation(...)` | **Write-Gated** | Idempotent state mutation gated behind mandatory human operator approval. |

---

## 4. Quickstart & One-Command Startup

### Prerequisites
- Docker & Docker Compose
- Python 3.11+
- (Optional) NVIDIA GPU with $\ge 12\text{ GB}$ VRAM for live local vLLM serving.

### Option A: One-Command Startup (Docker Compose)
Spins up PostgreSQL 16, Langfuse, automatically runs database seeding, and launches the FastAPI API and Chainlit console:
```bash
docker compose up -d
```
- **Chainlit SRE Console:** `http://localhost:8001`
- **FastAPI REST & SSE API:** `http://localhost:8000`
- **Interactive Swagger Docs:** `http://localhost:8000/docs`
- **Langfuse Observability:** `http://localhost:3000`

### Option B: Local Development Setup
```bash
# 1. Clone repository & setup virtual environment
git clone https://github.com/AmirRghp/omniops-sre-agent.git
cd omniops-sre-agent
make setup

# 2. Start PostgreSQL container
make docker-up

# 3. Seed operational services and incident logs
make seed

# 4. Launch Chainlit interactive console
make run-ui
```

---

## 5. Universal MCP Server Integration

Connect your favourite AI engineering IDE directly to the OmniOps MCP Server to diagnose live incidents and search runbooks from within your editor.

### 5.1 Cursor IDE Setup (`.cursor/mcp.json`)
```json
{
  "mcpServers": {
    "omniops-sre": {
      "command": "python",
      "args": ["-m", "src.mcp_server.server", "--transport", "stdio"],
      "env": {
        "DATABASE_URL": "postgresql+asyncpg://postgres:postgres@localhost:5432/omniops"
      }
    }
  }
}
```

### 5.2 Claude Desktop Setup (`claude_desktop_config.json`)
```json
{
  "mcpServers": {
    "omniops-sre": {
      "command": "python",
      "args": [
        "-m",
        "src.mcp_server.server",
        "--transport",
        "stdio"
      ],
      "cwd": "/path/to/omniops-sre-agent",
      "env": {
        "DATABASE_URL": "postgresql+asyncpg://postgres:postgres@localhost:5432/omniops"
      }
    }
  }
}
```

---

## 6. Chainlit Interactive SRE Console

The user console (`app.py`) adheres strictly to `docs/DESIGN_SYSTEM.md`:
- **Real-Time Tool Accordions:** Every MCP tool execution is rendered inside a `cl.Step` showing JSON inputs, formatted structured outputs, execution duration (ms), and circuit-breaker status badges (`[Mode: 🟢 Live OmniDoc RAG]` vs `[Mode: 🟡 Local Fallback Runbook]`).
- **HITL Approval Card:** Pauses with an elevated surface (`#1E293B`) and pulsing amber caution border (`#F59E0B`). Presents target service, proposed action, parameters, and idempotency key alongside `✅ تایید و اجرا (Approve)` and `❌ لغو عملیات (Reject)` buttons.
- **Bi-Directional Isolation:** Seamless RTL layout for Persian diagnostic reasoning paired with strict LTR code blocks for JSON, telemetry, and error codes.

---

## 7. Quantitative Agent Benchmark & Model Comparison

Evaluated across **25 multi-step bilingual scenarios** (`data/agent_eval_scenarios.json`) comparing `Qwen2.5-1.5B-Instruct-AWQ` against `Qwen2.5-7B-Instruct-AWQ` on a single 16GB VRAM GPU:

| Evaluation Metric | `Qwen2.5-1.5B-Instruct-AWQ` | `Qwen2.5-7B-Instruct-AWQ` | Production Floor | 7B Advantage |
| :--- | :---: | :---: | :---: | :--- |
| **Tool Selection Accuracy** | `88.0%` | **`100.0%`** | $\ge 92\%$ | **+12.0%** (Optimal tool chaining) |
| **Schema & Argument Validity** | `96.0%` | **`100.0%`** | $\ge 96\%$ | **+4.0%** (Zero hallucinated parameters) |
| **Fault Recovery Rate** | `60.0%` | **`100.0%`** | $\ge 88\%$ | **+40.0%** (Instant self-correction on typos) |
| **HITL Gate Interception** | **`100.0%`** | **`100.0%`** | $100\%$ | **Tied (100% Guaranteed by LangGraph)** |
| **P95 Latency (Inference)** | **`280ms`** | `420ms` | $\le 2000\text{ms}$ | **1.5B (~1.5x faster)** |
| **VRAM Footprint** | **`~1.4 GB`** | `~5.2 GB weights` | $\le 11\text{ GB}$ | **1.5B (lighter)** |

### Key Architectural Findings:
1. **Multi-Turn Schema Compliance:** The 7B model achieved 100% argument schema validity across all scenarios, whereas the 1.5B model hallucinated non-existent parameters on complex nested operations.
2. **Error Recovery Under Faults:** When presented with misspelled service names (`payment-service`), 7B immediately parsed the structured error `valid_services` and self-corrected on the next step.
3. **Architectural Safety:** Regardless of model size or prompt injection attempts, the state machine's graph-level checkpoint interrupt intercepted **100%** of write actions before execution.

Run the benchmark dry-run locally:
```bash
# Execute deterministic dry-run benchmark
make eval-dry-run

# Output comparative table
make eval-compare
```

---

## 8. Test Pyramid

```bash
# Run all 106 automated tests
pytest -v

# Run strict typechecking
mypy src evals app.py main.py

# Run linting and style checking
ruff check src tests evals app.py main.py
ruff format --check src tests evals app.py main.py
```

---

## 9. Limitations & Known Failure Modes

1. **Simulated State Mutations:** Remediations operate against a realistic PostgreSQL infrastructure state ledger rather than issuing raw root shell commands (`rm -rf` / `kubectl delete`) on host nodes to ensure sandbox safety.
2. **Local vLLM Concurrency:** In high-concurrency environments on 16GB VRAM, KV cache memory pressure can increase latency if context length exceeds 8192 tokens.
3. **Single-Region Checkpoint Store:** Checkpoints currently reside in a single PostgreSQL instance; production deployment across multi-region clusters would require distributed consensus (e.g. CockroachDB or AWS Aurora Global).

---

## 10. License

MIT License — see [LICENSE](LICENSE) for details.
