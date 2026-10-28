# Design System (DESIGN_SYSTEM.md)

## 1. Design Direction
- **Style:** Mission-Critical SRE Command Center, Minimalist, High-Contrast Dark Mode First.
- **Mood:** Authoritative, vigilant, structured, transparent, safe.
- **Design Principles:**
  - *Operational Visibility:* Every background tool invocation, argument payload, and execution latency must be inspectable without cluttering the main incident summary.
  - *High-Friction Consequential Gates:* State-changing actions (`execute_remediation`) must visually stand out with amber/crimson caution borders and unmistakable **Approve / Reject** controls.
  - *Bilingual Technical Precision:* Seamless RTL support for Persian incident descriptions paired with strict LTR alignment for JSON payloads, log lines, and service identifiers.

---

## 2. Brand
- **Brand Name:** OmniOps SRE Agent
- **Logo:** Monospace badge `[⚡ / OmniOps]` in Amber/Emerald on Obsidian Slate.
- **Brand Voice:** Calm, analytical, concise, safety-first.

---

## 3. Color Palette
- **Primary (Operational Active):** `#0EA5E9` (Sky 500 - Agent reasoning & read-only tool calls)
- **Secondary (Runbook / RAG Link):** `#10B981` (Emerald 500 - Connected to OmniDoc RAG)
- **Caution / Approval Gate:** `#F59E0B` (Amber 500 - Pending Human-in-the-Loop approval)
- **Danger / Critical Incident:** `#EF4444` (Red 500 - Service CRITICAL state or rejected remediation)
- **Background (Dark):** `#0B0F19` (Deep Command Center Obsidian)
- **Background (Light):** `#F8FAFC` (Slate 50)
- **Surface / Card (Dark):** `#111827` (Gray 900)
- **Elevated Surface / Approval Modal:** `#1E293B` (Slate 800)
- **Text Primary:** `#F8FAFC` (Dark Mode) / `#0F172A` (Light Mode)
- **Text Muted:** `#94A3B8` (Slate 400)
- **Border Default:** `#1E293B`
- **Border Approval Gate:** `#F59E0B` (2px solid with subtle pulse glow)

---

## 4. Typography
- **Primary Persian Font:** `Vazirmatn`, sans-serif (400, 500, 700)
- **Primary English UI Font:** `Inter`, system-ui, sans-serif
- **Telemetry, Logs & JSON Payloads:** `JetBrains Mono`, `Fira Code`, monospace
- **Scale:**
  - **H1 (Incident Title):** 26px / 700 / Line Height 1.3
  - **H2 (Section Header):** 20px / 600 / Line Height 1.35
  - **H3 (Card & Tool Header):** 16px / 600 / Line Height 1.4
  - **Body (Diagnosis & Explanation):** 15px / 400 / Line Height 1.65
  - **Monospace Payloads & Logs:** 13px / 400 / Line Height 1.5

---

## 5. Spacing & Layout
- **Base Unit:** 4px (`xs: 4px`, `sm: 8px`, `md: 12px`, `base: 16px`, `lg: 24px`, `xl: 32px`).
- **Max Chat Width:** 900px centered for readability of wide log tables and JSON blocks.

---

## 6. Component Specifications

### 6.1 MCP Tool Execution Step (Chainlit Accordion)
- **Header:** `[Tool Icon] Tool Name` + `[Badge: Read-Only | Write-Gated]` + `[Execution Time: e.g., 42ms]`.
- **Fallback Indicator:** When `search_runbooks` uses the local fallback instead of Live Project 1, display pill: `[Mode: Local Fallback Runbook]`. When connected to Project 1, display emerald pill: `[Mode: Live OmniDoc RAG]`.
- **Body:** Split view with `Input Arguments (JSON)` and `Structured Output (JSON)`.

### 6.2 Human-in-the-Loop (HITL) Approval Card
- **Container:** `#1E293B` surface, 2px solid `#F59E0B` border, 12px border radius, `16px` padding.
- **Header:** `⚠️ نیاز به تایید اپراتور (Human Approval Required)`
- **Metadata Table:**
  - **Target Service:** Monospace badge (e.g., `payment-api`)
  - **Proposed Action:** Monospace badge (e.g., `increase_db_pool`)
  - **Parameters:** `{"new_pool_size": 50}`
  - **Idempotency Key:** `idem_9f8a7d6c`
  - **Justification:** Clear explanation grounded in retrieved logs and runbooks.
- **Action Buttons:**
  - **Approve (`تایید و اجرا`):** Solid Emerald (`#10B981`), bold white text, icon `CheckCircle`.
  - **Reject (`لغو عملیات`):** Solid Rose (`#EF4444`), bold white text, icon `XCircle`.

---

## 7. Accessibility & Bi-Directional Rules
- All Persian natural language explanations render `dir="rtl"`.
- All JSON tool inputs/outputs, SQL log tables, and service identifiers (`payment-api`, `ERR_DB_POOL_EXHAUSTED`) render strictly `dir="ltr"` inside isolated `<pre><code>` blocks.
