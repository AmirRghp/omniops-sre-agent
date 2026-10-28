# User Experience & Agent Execution Flows (UX_FLOWS.md)

## Overview
This document traces the interactive user and system flows across the OmniOps SRE Agent, detailing how multi-step tool calling, self-correction, circuit-breaker fallbacks, and Human-in-the-Loop (HITL) approvals behave in real time.

---

## Flow 1 — End-to-End Incident Diagnosis & Approved Remediation (Happy Path)
*An SRE reports a production incident; the agent investigates via read-only MCP tools, consults the runbook, pauses for human approval, and executes the fix.*

```
[SRE User Input]: "سرویس payment-api کند شده و کاربران خطای 502 می‌گیرند. بررسی کن."
       │
       ▼
[LangGraph Node: agent_planner]
       ├── Step 1 (MCP Tool): `get_service_health(service_name="payment-api")`
       │     └── Output: `status="DEGRADED", p95_latency_ms=4200, cpu_pct=35, active_connections=100/100`
       │
       ├── Step 2 (MCP Tool): `query_incident_logs(service_name="payment-api", severity="ERROR", limit=5)`
       │     └── Output: `ERR_DB_POOL_EXHAUSTED: QueuePool limit of size 100 overflow 0 reached`
       │
       └── Step 3 (MCP Tool): `search_runbooks(query="ERR_DB_POOL_EXHAUSTED payment-api connection pool")`
             └── Output (from OmniDoc RAG / Fallback): "Runbook RB-104: When ERR_DB_POOL_EXHAUSTED occurs with low CPU, increase db_pool_size to 200 and flush stale connections."
       │
       ▼
[LangGraph Node: agent_planner proposes `execute_remediation`]
       │
       ▼
[LangGraph Checkpoint & Interrupt (`interrupt_before=["execute_remediation_node"]`)]
       │
       ▼
[Chainlit UI Renders Approval Card]:
       ├── Target: `payment-api`
       ├── Action: `increase_db_pool` (`{"pool_size": 200}`)
       ├── Idempotency Key: `idem_pay_pool_20261028`
       └── Buttons: [✅ Approve & Execute]   [❌ Reject Action]
       │
       ▼ (User clicks ✅ Approve & Execute)
[LangGraph Resumes from Postgres Checkpoint]
       │
       ▼
[MCP Tool Executes: `execute_remediation` -> Updates PostgreSQL Service State]
       │
       ▼
[Post-Remediation Verification]:
       └── Agent calls `get_service_health("payment-api")` -> `status="HEALTHY", p95_latency_ms=145`
       │
       ▼
[Final Grounded Incident Report Rendered to User]
```

---

## Flow 2 — Human Rejection & Safe Abort Flow
*The SRE disagrees with the proposed remediation and clicks Reject.*

```
[Approval Card Displayed for `execute_remediation(action_type="restart_service")`]
       │
       ▼ (User clicks ❌ Reject Action with optional note: "الان پیک ترافیک است، ری‌استارت نکن")
[LangGraph Resumes with ToolMessage: `{"status": "REJECTED_BY_OPERATOR", "reason": "Peak traffic window"}`]
       │
       ▼
[Agent Acknowledges Rejection]:
       └── Generates safe manual escalation summary without calling any write tool.
```

---

## Flow 3 — Self-Healing Tool Error Recovery (Hallucinated Argument)
*The LLM initially guesses an incorrect service name (`"payment-service"` instead of `"payment-api"`).*

```
[Agent calls `get_service_health(service_name="payment-service")`]
       │
       ▼
[MCP Tool Validation catches mismatch (No raw exception thrown)]
       └── Returns Structured Error JSON:
           `{"status": "error", "code": "SERVICE_NOT_FOUND", "message": "Service 'payment-service' does not exist.", "valid_services": ["payment-api", "auth-service", "postgres-primary", "redis-cache", "nginx-ingress"]}`
       │
       ▼
[UI Step Badge shows Amber Warning: "Tool returned SERVICE_NOT_FOUND -> Agent self-correcting..."]
       │
       ▼
[Agent reads `valid_services` and immediately calls `get_service_health(service_name="payment-api")`]
       │
       ▼
[Execution succeeds seamlessly]
```

---

## Flow 4 — Circuit Breaker Fallback to Local Runbooks (Project 1 Offline)
*A reviewer clones and runs only Project 2 (`OmniOps SRE Agent`) without starting Project 1 (`OmniDoc RAG`).*

```
[Agent invokes MCP Tool: `search_runbooks(query="redis memory eviction OOM")`]
       │
       ▼
[RunbookClient pings `http://localhost:8080/api/v1/query` (Timeout: 1.5s)]
       ├── Connection Refused / Offline
       ▼
[Circuit Breaker trips to `OPEN` state -> Routes query to Local BM25/Keyword Runbook Store (`data/fallback_runbooks.json`)]
       │
       ▼
[Returns matching Runbook chunk + Metadata `source_mode: "LOCAL_FALLBACK"`]
       │
       ▼
[UI displays subtle info badge: "Runbook retrieved via Local Standalone Fallback"]
```

---

## Flow 5 — Runaway Loop Prevention (Hard Step Ceiling)
*An adversarial or unsolvable prompt attempts to trap the agent in an endless tool-calling loop.*

```
[Agent reaches `step_count == 6` (`MAX_STEPS` ceiling)]
       │
       ▼
[LangGraph Conditional Edge forces route to `force_terminate_node`]
       │
       ▼
[Agent outputs partial findings collected so far + explicit warning that step budget (6/6) was reached]
```
