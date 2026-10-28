# API & MCP Tool Contracts (API.md)

## 1. Overview
OmniOps SRE Agent exposes two contract layers:
1. **Model Context Protocol (MCP) Tool Contracts:** Used by the internal LangGraph agent AND external MCP clients (Cursor, Claude Desktop).
2. **FastAPI REST & SSE Endpoints:** Used by the Chainlit UI and automated evaluation scripts.

---

## 2. MCP Server Tool Specifications (`src/mcp_server/tools.py`)

### 2.1 Tool: `search_runbooks` (Read-Only)
Searches standard operating procedures (SOPs) and technical troubleshooting runbooks.
- **Input Schema:**
  ```json
  {
    "type": "object",
    "properties": {
      "query": {
        "type": "string",
        "description": "Technical error code, symptom, or infrastructure keyword (e.g., 'ERR_DB_POOL_EXHAUSTED' or 'Nginx 502 Bad Gateway')."
      },
      "category": {
        "type": "string",
        "enum": ["database", "networking", "containers", "caching", "general"],
        "description": "Optional infrastructure domain filter."
      }
    },
    "required": ["query"]
  }
  ```
- **Output Schema:**
  ```json
  {
    "status": "success",
    "source_mode": "LIVE_OMNIDOC_RAG",
    "results": [
      {
        "runbook_id": "RB-104",
        "title": "Resolving Database Connection Pool Exhaustion",
        "content": "When ERR_DB_POOL_EXHAUSTED occurs and CPU is below 50%, do not restart the database. Increase db_pool_size to 200.",
        "relevance_score": 0.94
      }
    ]
  }
  ```

---

### 2.2 Tool: `query_incident_logs` (Read-Only)
Fetches recent structured logs for a specific microservice from PostgreSQL.
- **Input Schema:**
  ```json
  {
    "type": "object",
    "properties": {
      "service_name": {
        "type": "string",
        "description": "Exact microservice identifier (e.g., 'payment-api', 'auth-service', 'redis-cache', 'postgres-primary', 'nginx-ingress')."
      },
      "severity": {
        "type": "string",
        "enum": ["WARN", "ERROR", "CRITICAL"],
        "default": "ERROR"
      },
      "limit": {
        "type": "integer",
        "minimum": 1,
        "maximum": 20,
        "default": 5
      }
    },
    "required": ["service_name"]
  }
  ```
- **Structured Error Response (Self-Correction Contract):**
  ```json
  {
    "status": "error",
    "error_code": "SERVICE_NOT_FOUND",
    "message": "Service 'payment' not found in infrastructure registry.",
    "valid_services": ["payment-api", "auth-service", "postgres-primary", "redis-cache", "nginx-ingress"]
  }
  ```

---

### 2.3 Tool: `get_service_health` (Read-Only)
Retrieves real-time resource utilization, replica counts, connection pools, and status of a microservice.
- **Input Schema:**
  ```json
  {
    "type": "object",
    "properties": {
      "service_name": {
        "type": "string",
        "description": "Exact microservice identifier."
      }
    },
    "required": ["service_name"]
  }
  ```
- **Output Schema:**
  ```json
  {
    "status": "success",
    "service": {
      "service_name": "payment-api",
      "health_status": "DEGRADED",
      "cpu_usage_pct": 34.5,
      "memory_usage_mb": 1024,
      "memory_limit_mb": 2048,
      "p95_latency_ms": 4200,
      "active_replicas": 3,
      "max_replicas": 6,
      "db_pool_size": 100,
      "active_connections": 100
    }
  }
  ```

---

### 2.4 Tool: `execute_remediation` (Write / HITL-Gated / Idempotent)
Executes a state-changing remediation command on a target service.
- **Input Schema:**
  ```json
  {
    "type": "object",
    "properties": {
      "service_name": {
        "type": "string",
        "description": "Target microservice name."
      },
      "action_type": {
        "type": "string",
        "enum": ["restart_service", "scale_replicas", "flush_redis_cache", "increase_db_pool"],
        "description": "Specific remediation operation to perform."
      },
      "parameters": {
        "type": "object",
        "description": "Action parameters, e.g., {'pool_size': 200} or {'replicas': 4}."
      },
      "idempotency_key": {
        "type": "string",
        "description": "Unique deterministic key for this action (e.g., 'idem_payment_api_increase_pool_200')."
      },
      "reason": {
        "type": "string",
        "description": "Evidence-based explanation citing the log error code and runbook ID."
      }
    },
    "required": ["service_name", "action_type", "parameters", "idempotency_key", "reason"]
  }
  ```

---

## 3. FastAPI REST & Streaming Endpoints (`src/api/routes.py`)

### 3.1 `POST /api/v1/incident/stream`
Starts or continues an incident investigation thread and streams SSE events (`tool_call`, `tool_result`, `approval_required`, `token`, `done`).
- **Request Body:**
  ```json
  {
    "query": "سرویس پرداخت کند شده و خطای 502 می‌دهد. بررسی و رفع کن.",
    "thread_id": "inc_20261028_001"
  }
  ```

### 3.2 `POST /api/v1/incident/approve`
Resumes a paused LangGraph thread waiting at the Human-in-the-Loop interrupt gate.
- **Request Body:**
  ```json
  {
    "thread_id": "inc_20261028_001",
    "decision": "APPROVE",
    "operator_id": "sre_admin",
    "comment": "Approved after verifying RB-104."
  }
  ```

### 3.3 `POST /api/v1/infra/reset`
Resets PostgreSQL operational tables back to initial seed state (used between evaluation runs and demos).
