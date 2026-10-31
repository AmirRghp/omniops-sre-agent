# Ecosystem Integration Guide: Running OmniDoc RAG & OmniOps SRE Agent Together

> **Comprehensive, step-by-step walkthrough for deploying, connecting, and testing Project 1 (`OmniDoc RAG`) and Project 2 (`OmniOps SRE Agent`) simultaneously on a single workstation (e.g., Windows with 16GB VRAM GPU).**

---

## 1. System Architecture & Resource Allocation

When running both projects together, the system operates as a unified AI engineering ecosystem:
- **Project 1 (`OmniDoc RAG`):** Serves technical runbooks, multilingual system guides, and hybrid search (BM25 + BAAI/bge-m3 dense vector embeddings in Qdrant) over HTTP API on port **`8080`**.
- **Project 2 (`OmniOps SRE Agent`):** Stateful LangGraph agent with PostgreSQL checkpoints and FastMCP tools. Queries OmniDoc RAG via an automated **Circuit Breaker** on port `8080` (with transparent fallback to local JSON if offline), pausing at the Human-in-the-Loop (HITL) gate in the Chainlit console on port **`8001`**.
- **LLM Serving (`vLLM`):** Single shared local instance serving `Qwen/Qwen2.5-7B-Instruct-AWQ` on port **`8000`** with `--gpu-memory-utilization 0.60` (~9.9GB total VRAM used, leaving >6GB safety headroom on a 16GB GPU).

```
┌──────────────────────────────────────────────────────────────────────────┐
│                   Local Host (16GB VRAM GPU Workstation)                 │
├───────────────────────────┬──────────────────────────────────────────────┤
│ Project 1: OmniDoc RAG    │ Project 2: OmniOps SRE Agent                 │
│                           │                                              │
│ - FastAPI Service (:8080) │ - Chainlit Web UI (:8001)                    │
│ - Qdrant Vector DB (:6333)│ - PostgreSQL 16 (:5432)                      │
│ - Redis Cache (:6379)     │ - FastMCP Tool Engine                        │
│ - BGE-M3 Embeddings (CPU) │ - LangGraph AsyncPostgres State Machine      │
├───────────────────────────┴──────────────────────────────────────────────┤
│ Shared Inference Engine:                                                 │
│ - vLLM OpenAI-Compatible Server (:8000) -> Qwen2.5-7B-Instruct-AWQ       │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Port Map & Shared Infrastructure

| Service | Port | Host Address | Purpose |
| :--- | :---: | :--- | :--- |
| **vLLM (Local LLM)** | `8000` | `http://localhost:8000/v1` | OpenAI-compatible inference for both projects |
| **OmniDoc RAG API** | `8080` | `http://localhost:8080` | Technical documentation and runbook search endpoint |
| **OmniOps Chainlit UI** | `8001` | `http://localhost:8001` | Interactive SRE agent console & HITL approval cards |
| **PostgreSQL 16** | `5432` | `localhost:5432` | OmniOps operational tables & LangGraph checkpoints |
| **Qdrant Vector DB** | `6333` | `localhost:6333` | OmniDoc RAG dense vectors & payload storage |
| **Redis Cache** | `6379` | `localhost:6379` | OmniDoc semantic cache & query deduplication |

---

## 3. Step-by-Step Setup Guide

### Step 1: Start Shared Infrastructure & vLLM Serving

Open **Terminal 1** and start the Docker containers for PostgreSQL, Qdrant, Redis, and vLLM:

#### 1.1 Start Databases (PostgreSQL, Qdrant, Redis)
```powershell
# PostgreSQL for OmniOps (port 5432)
docker run -d --name omniops-postgres `
  -e POSTGRES_DB=omniops `
  -e POSTGRES_USER=postgres `
  -e POSTGRES_PASSWORD=postgres `
  -p 5432:5432 `
  postgres:16-alpine

# Qdrant for OmniDoc (port 6333)
docker run -d --name omnidoc-qdrant `
  -p 6333:6333 -p 6334:6334 `
  qdrant/qdrant:v1.11.0

# Redis for OmniDoc (port 6379)
docker run -d --name omnidoc-redis `
  -p 6379:6379 `
  redis:7-alpine
```

#### 1.2 Start vLLM Model Server (Qwen2.5-7B-Instruct-AWQ)
```powershell
docker run --rm -it --name omniops-vllm `
  --gpus all `
  -p 8000:8000 `
  -v C:\Users\Amirreza\.cache\huggingface:/root/.cache/huggingface `
  vllm/vllm-openai:latest `
  --model Qwen/Qwen2.5-7B-Instruct-AWQ `
  --quantization awq `
  --dtype half `
  --gpu-memory-utilization 0.60 `
  --max-model-len 8192 `
  --enable-auto-tool-choice `
  --tool-call-parser hermes
```
*Wait until vLLM outputs `Application startup complete` and models are visible at `http://localhost:8000/v1/models`.*

---

### Step 2: Ingest Runbooks & Launch Project 1 (`OmniDoc RAG`)

Open **Terminal 2** to setup and start the OmniDoc RAG service:

```powershell
# 1. Navigate to OmniDoc repository
cd d:\Work\omnidoc-rag

# 2. Activate Python virtual environment
.\.venv\Scripts\Activate.ps1

# 3. Verify .env file configuration
# Ensure LLM_BASE_URL=http://localhost:8000/v1 and API_KEY=dev_insecure_local_key_replace_in_prod

# 4. Ingest runbooks into Qdrant & build BM25 sparse index (Run once)
python -m src.ingestion.pipeline

# 5. Launch OmniDoc API on port 8080 (Press CTRL+C when you want to quit)
uvicorn src.main:app --host 127.0.0.1 --port 8080
```

Verify OmniDoc health in PowerShell:
```powershell
curl http://127.0.0.1:8080/health
# Expected: {"status":"healthy", ...}
```

---

### Step 3: Seed Database & Launch Project 2 (`OmniOps SRE Agent`)

Open **Terminal 3** to initialize OmniOps:

```powershell
# 1. Navigate to OmniOps repository
cd d:\Work\omniops-sre-agent

# 2. Activate Python virtual environment
.\.venv\Scripts\Activate.ps1

# 3. Verify .env file configuration:
# DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/omniops
# SYNC_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/omniops
# LLM_BASE_URL=http://localhost:8000/v1
# OMNIDOC_RAG_URL=http://localhost:8080/api/v1/query
# API_KEY=dev_insecure_local_key_replace_in_prod
# MAX_AGENT_TOKENS=8192

# 4. Seed initial microservices and incident logs into PostgreSQL
python -m src.db.seed

# 5. Launch the interactive Chainlit SRE Console on port 8001
python run_app.py
```

Console is now accessible at: **`http://localhost:8001`**.

---

## 4. End-to-End Verification & Interactive HITL Test

To verify the live integration between both projects:

1. Open **`http://localhost:8001`** in your browser.
2. Submit this prompt in Persian or English:
   > **سرویس payment-api دچار خطای ERR_DB_POOL_EXHAUSTED شده است. وضعیت را بررسی کن، کتابچه راهنما را جستجو کن و عملیات رفع مشکل را انجام بده.**
3. **Observe the Tool Call Stream:**
   - `get_service_health` checks `payment-api` (returns `DEGRADED`, connections = 100/100).
   - `query_incident_logs` fetches `ERR_DB_POOL_EXHAUSTED` stack traces.
   - `search_runbooks` calls Project 1 over port 8080 and displays:
     ```
     Used 🔍 search_runbooks • [Mode: 🟢 Live OmniDoc RAG]
     ```
     Citing runbook `RB-104` with connection pool recommendations.
4. **Human-in-the-Loop (HITL) Gate:**
   - LangGraph pauses execution before `remediation_node`.
   - The UI displays the interactive approval card with target parameters (`pool_size: 200`) and idempotency key (`idem_payment-api_increase_db_pool_200`).
5. **Approve Action:**
   - Click **`✅ تایید و اجرا (Approve)`**.
   - OmniOps executes the mutation on PostgreSQL, updates `db_pool_size` to `200`, sets service status to `HEALTHY`, records an immutable audit ledger row, and outputs the final Persian resolution report.

---

## 5. Circuit Breaker Fallback Verification

To test standalone resilience when Project 1 is unavailable:

1. In **Terminal 2**, stop the OmniDoc server (`Ctrl + C`).
2. In the Chainlit console, run an incident inquiry.
3. Observe `search_runbooks` output badge:
   ```
   Used 🔍 search_runbooks • [Mode: 🟡 Local Fallback Runbook]
   ```
   The Circuit Breaker automatically falls back to `data/fallback_runbooks.json` within 2.5 seconds without crashing the agent or failing the investigation.

---

## 6. Running the Automated Evaluation Suite

To run the full 25-scenario benchmark against the live ecosystem:

```powershell
cd d:\Work\omniops-sre-agent
python -m evals.run_agent_benchmark --model Qwen/Qwen2.5-7B-Instruct-AWQ --output evals/results/eval_7b.json
```

Target benchmarks:
- **Schema & Argument Validity:** `100.0%`
- **HITL Interception Rate:** `100.0%`
- **Adversarial Prompt Defense:** `100.0%`
- **Tool Selection Accuracy:** `84.0%`
