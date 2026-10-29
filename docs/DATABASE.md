# Database & State Storage Specification (DATABASE.md)

## 1. Database Overview
OmniOps SRE Agent uses **PostgreSQL 16** as its single unified relational and state persistence engine:
1. **Operational Infrastructure State:** Simulated live services, container health metrics, and incident error logs that the MCP tools inspect and mutate.
2. **Remediation Audit & Idempotency Ledger:** Tracks every proposed, approved, rejected, and executed action with unique idempotency keys.
3. **LangGraph Checkpoint Store:** Managed by `langgraph-checkpoint-postgres` (`checkpoints`, `checkpoint_blobs`, `checkpoint_writes`) to freeze and resume agent state across Human-in-the-Loop interrupts.

---

## 2. Naming & Schema Conventions
- **Table Names:** Plural `snake_case` (`infra_services`, `incident_logs`, `remediation_executions`).
- **Primary Keys:** UUIDv4 or deterministic string identifiers.
- **Timestamps:** `TIMESTAMP WITH TIME ZONE` in UTC (`created_at`, `updated_at`).

---

## 3. Operational Tables Schema

### 3.1 Table: `infra_services`
Stores the current live health and configuration parameters of monitored microservices.

```sql
CREATE TABLE infra_services (
    service_name VARCHAR(64) PRIMARY KEY, -- e.g., 'payment-api', 'auth-service', 'postgres-primary', 'redis-cache', 'nginx-ingress'
    status VARCHAR(24) NOT NULL CHECK (status IN ('HEALTHY', 'DEGRADED', 'CRITICAL', 'RESTARTING')),
    cpu_usage_pct NUMERIC(5, 2) NOT NULL,
    memory_usage_mb INTEGER NOT NULL,
    memory_limit_mb INTEGER NOT NULL,
    p95_latency_ms INTEGER NOT NULL,
    active_replicas INTEGER NOT NULL,
    max_replicas INTEGER NOT NULL,
    db_pool_size INTEGER NOT NULL DEFAULT 100,
    active_connections INTEGER NOT NULL DEFAULT 20,
    last_restarted_at TIMESTAMP WITH TIME ZONE,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
```

### 3.2 Table: `incident_logs`
Stores time-series operational logs and error codes queried by `query_incident_logs`.

```sql
CREATE TABLE incident_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    service_name VARCHAR(64) NOT NULL REFERENCES infra_services(service_name) ON DELETE CASCADE,
    severity VARCHAR(16) NOT NULL CHECK (severity IN ('INFO', 'WARN', 'ERROR', 'CRITICAL')),
    error_code VARCHAR(64) NOT NULL,      -- e.g., 'ERR_DB_POOL_EXHAUSTED', 'ERR_REDIS_OOM', 'HTTP_502_BAD_GATEWAY'
    message TEXT NOT NULL,
    trace_id VARCHAR(64),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_incident_logs_service_severity ON incident_logs(service_name, severity, created_at DESC);
CREATE INDEX idx_incident_logs_error_code ON incident_logs(error_code);
```

### 3.3 Table: `remediation_executions` (Idempotency & Audit Ledger)
Ensures no remediation action is executed twice on network retries and maintains a complete security audit trail.

```sql
CREATE TABLE remediation_executions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    idempotency_key VARCHAR(128) UNIQUE NOT NULL,
    thread_id VARCHAR(128) NOT NULL,
    service_name VARCHAR(64) NOT NULL REFERENCES infra_services(service_name) ON DELETE CASCADE,
    action_type VARCHAR(64) NOT NULL CHECK (action_type IN ('restart_service', 'scale_replicas', 'flush_redis_cache', 'increase_db_pool')),
    parameters JSONB NOT NULL DEFAULT '{}'::jsonb,
    reason TEXT NOT NULL,
    approval_status VARCHAR(24) NOT NULL CHECK (approval_status IN ('PENDING', 'APPROVED', 'REJECTED')),
    approved_by VARCHAR(64),
    execution_result JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    executed_at TIMESTAMP WITH TIME ZONE
);

CREATE UNIQUE INDEX idx_remediation_idempotency ON remediation_executions(idempotency_key);
```

---

## 4. Seed Data Scenarios (`src/db/seed.py`)
To make manual testing and automated benchmarking immediately reproducible, `seed.py` populates 5 realistic services and 3 active incident scenarios:
1. **Scenario A (`payment-api`):** Status `DEGRADED`, `p95_latency_ms = 4200`, `active_connections = 100/100`, logs filled with `ERR_DB_POOL_EXHAUSTED`. (Expected fix: `increase_db_pool` to 200).
2. **Scenario B (`redis-cache`):** Status `CRITICAL`, `memory_usage_mb = 4090/4096`, logs filled with `ERR_REDIS_OOM_EVICTION`. (Expected fix: `flush_redis_cache`).
3. **Scenario C (`auth-service`):** Status `DEGRADED`, `cpu_usage_pct = 96.5%`, `active_replicas = 2/8`, logs showing `WARN_HIGH_CPU_THROTTLING`. (Expected fix: `scale_replicas` to 4).
4. **Healthy Services (`postgres-primary`, `nginx-ingress`):** Status `HEALTHY` for negative-control testing.
