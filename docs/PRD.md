# Product Requirements Document (PRD)

## 1. Product Overview
- **Product Name:** OmniOps SRE Agent (Autonomous Incident Response & MCP Platform)
- **One-Line Description:** A production-hardened, bilingual (Persian/English) AI SRE Agent powered by LangGraph and Model Context Protocol (MCP) that autonomously diagnoses infrastructure incidents, queries live operational telemetry, consults technical runbooks, and executes remediation actions behind a strict Human-in-the-Loop (HITL) approval gate.
- **Product Type:** Autonomous DevOps / SRE Platform & Standardized MCP Server
- **Primary Platform:** Web Application (FastAPI + Chainlit Interactive UI) + Standalone MCP Server (Stdio & Streamable HTTP/SSE Transports)

---

## 2. Problem
### What problem are we solving?
1. **Fragmented Incident Triage:** During an outage, SREs must manually jump between log tables, container metric dashboards, and Markdown documentation runbooks to diagnose root causes.
2. **Fragile Demo Agents:** Most portfolio "AI Agents" only showcase happy-path tool calling. They crash on malformed tool arguments, infinite loop when an API fails, or execute destructive commands without human oversight.
3. **Siloed Tool Implementations:** Custom Python functions hardwired into a single agent script cannot be reused across external AI clients like Claude Desktop or Cursor.
4. **Lack of Quantitative Agent Evaluation:** Very few engineering portfolios measure deterministic tool selection accuracy, schema compliance, fault recovery rate, or compare small vs. medium local model capabilities (`1.5B` vs. `7B`).

### Why does this problem matter?
In production infrastructure, an unconstrained AI agent executing an unverified restart or database configuration change can cause catastrophic downtime or duplicate side effects. Engineering teams require deterministic tool interfaces (MCP), idempotent execution, hard step/token ceilings, and mandatory human approval checkpoints.

---

## 3. Goals
### Primary Goal
Build an autonomous, fault-tolerant SRE Agent and standalone MCP Server that achieves $\ge 92\%$ multi-step tool selection accuracy, $100\%$ human-gate interception on write actions, and $100\%$ idempotent execution on retries, verified via an automated evaluation suite.

### Secondary Goals
- Seamlessly integrate with Project 1 (`OmniDoc RAG`) via an intelligent Circuit Breaker with a local standalone fallback so the repository runs 100% self-contained.
- Stay comfortably within a 16GB VRAM budget using local vLLM serving (`Qwen2.5-Instruct-AWQ` family).
- Benchmark and document the empirical capability gap between `Qwen2.5-1.5B-Instruct-AWQ` and `Qwen2.5-7B-Instruct-AWQ` on complex multi-step tool calling.

---

## 4. Target Users
### User Type 1: Site Reliability Engineers (SREs) & DevOps Teams
- **Needs:** Automated root-cause correlation across logs, metrics, and runbooks, with a safe one-click approval button for remediation.
- **Pain Points:** Alert fatigue, slow manual log correlation, risk of running the wrong command under pressure.

### User Type 2: AI Engineering Hiring Managers & Staff Engineers
- **Needs:** Proof that the candidate understands MCP tool design, durable state machines (`LangGraph`), idempotency, structured error recovery, and rigorous agent evaluation.

---

## 5. User Stories
- **US-01 (Multi-Step Root Cause Analysis):** As an SRE, I want to report an alert (in Persian or English, e.g., *"سرویس پرداخت کند شده و خطای ۵۰۲ می‌دهد"*) so the agent automatically checks service health, queries recent error logs, and retrieves the matching remediation runbook.
- **US-02 (Human-in-the-Loop Safety Gate):** As an SRE, when the agent proposes a state-changing action (e.g., restarting a container or scaling connection pools), I want the workflow to pause and present an explicit **Approve / Reject** card in the UI before anything executes.
- **US-03 (Self-Healing Tool Recovery):** As a developer, if the model passes an invalid service name or a tool encounters a transient failure, I want the tool to return a structured, actionable error message so the agent self-corrects on the next turn without crashing.
- **US-04 (Universal MCP Compatibility):** As an engineer using Cursor or Claude Desktop, I want to connect directly to the `OmniOps MCP Server` to query infrastructure logs and runbooks from my IDE.
- **US-05 (Deterministic Agent Benchmarking):** As an AI engineer, I want to run `make eval` to measure Tool Selection Accuracy, Argument Validity, and Error Recovery across 25 multi-step incident scenarios.

---

## 6. Core Features

### Feature 1: Standardized MCP Server with 4 Narrow Tools
- **Purpose:** Expose narrow, strictly typed, single-responsibility tools via the official Model Context Protocol.
- **Tools:**
  1. `search_runbooks(query: str, category: Optional[str])`: Queries Project 1 (`OmniDoc RAG`) live API if reachable; automatically falls back to a built-in local runbook store if Project 1 is offline.
  2. `query_incident_logs(service_name: str, severity: Literal["ERROR", "WARN", "CRITICAL"], limit: int)`: Queries PostgreSQL operational logs with strict parameter validation.
  3. `get_service_health(service_name: str)`: Fetches real-time CPU, RAM, P95 latency, replica count, and container status from PostgreSQL.
  4. `execute_remediation(service_name: str, action_type: Literal["restart_service", "scale_replicas", "flush_redis_cache", "increase_db_pool"], parameters: dict, idempotency_key: str, reason: str)`: Executes a state-changing remediation action.
- **Acceptance Criteria:** Zero multi-purpose `mode` flags; 100% Pydantic schema validation; runnable standalone via Stdio and Streamable HTTP/SSE.

### Feature 2: LangGraph State Machine with Durable Checkpointing & HITL Interrupts
- **Purpose:** Orchestrate multi-step reasoning (`Plan -> Call Read Tools -> Synthesize -> Propose Write Tool -> Pause for Human -> Execute -> Verify`).
- **Acceptance Criteria:**
  - Uses `AsyncPostgresSaver` for persistent state checkpointing across turns.
  - Triggers `interrupt_before=["execute_remediation_node"]` whenever a write tool is invoked.
  - Enforces a hard ceiling of `MAX_STEPS = 6` and `MAX_TOKENS_PER_INCIDENT = 4096` to prevent runaway loops.

### Feature 3: Structured Tool Error Recovery & Idempotency
- **Purpose:** Ensure production resilience under malformed LLM outputs and network retries.
- **Acceptance Criteria:**
  - If `service_name` does not exist, tool returns `{"status": "error", "error_code": "SERVICE_NOT_FOUND", "valid_services": ["payment-api", "auth-service", "postgres-primary", "redis-cache", "nginx-ingress"]}` instead of raising an unhandled exception.
  - `execute_remediation` checks `idempotency_key` in PostgreSQL; duplicate keys return the cached execution result without re-running the action.

### Feature 4: Interactive Chainlit Incident Console
- **Purpose:** Visualize every tool call, input payload, structured output, fallback status, and interactive **Approve / Reject** action buttons.

### Feature 5: Automated Agent Evaluation & Model Comparison Suite
- **Purpose:** Quantitatively prove agent reliability and compare `Qwen2.5-1.5B-AWQ` vs. `Qwen2.5-7B-AWQ`.
- **Metrics:** Tool Selection Accuracy, Schema Compliance Rate, Self-Correction Recovery Rate, Hallucinated Tool Rate, and P95 Latency.

---

## 7. Non-Goals (Out of Scope)
- Executing real destructive shell commands (`rm -rf`, raw `kubectl delete`) on the host OS (remediations operate safely against a realistic simulated infrastructure state in PostgreSQL).
- Multi-agent swarm debates (a single deterministic state machine is cleaner, faster, and more reliable for SRE triage).
- Multimodal diagram parsing (reserved for Project 3).

---

## 8. Success Metrics
- **Tool Selection Accuracy:** $\ge 92\%$ (with `Qwen2.5-7B-Instruct-AWQ`)
- **Argument Schema Validity:** $\ge 96\%$
- **Error Recovery Rate (Fault Injection):** $\ge 85\%$
- **Human-Gate Interception Rate:** $100\%$ (Zero unapproved write executions)
- **Idempotency Protection:** $100\%$ (Zero duplicate side-effects on retry)
- **VRAM Footprint:** $\le 11\text{ GB}$ total (fitting easily inside 16GB VRAM)

---

## 9. Definition of Done (DoD)
- [ ] All 4 MCP tools implemented, unit-tested without an LLM in the loop, and exposed via MCP Server.
- [ ] Circuit breaker cleanly switches between Live `OmniDoc RAG` (port 8080) and Local Fallback Runbooks.
- [ ] LangGraph workflow persists state in PostgreSQL and pauses before `execute_remediation`.
- [ ] Chainlit UI renders live tool steps and interactive Approve/Reject buttons.
- [ ] Evaluation benchmark script runs 25 scenarios and outputs side-by-side metrics (`1.5B` vs. `7B`).
- [ ] `ruff`, `mypy`, and `pytest` pass with 0 errors.
