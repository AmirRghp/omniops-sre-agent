"""Formatting and presentation utilities for the Chainlit SRE console."""

import json
from collections.abc import Mapping
from typing import Any

from src.agent.nodes import READ_ONLY_TOOLS
from src.agent.state import PendingRemediation

TOOL_ICONS: dict[str, str] = {
    "get_service_health": "📊",
    "query_incident_logs": "📜",
    "search_runbooks": "🔍",
    "execute_remediation": "⚙️",
}


def get_mode_badge(source_mode: str | None) -> str:
    """Return a styled status pill for runbook retrieval modes."""
    if source_mode == "LIVE_OMNIDOC_RAG":
        return "[Mode: 🟢 Live OmniDoc RAG]"
    if source_mode == "LOCAL_FALLBACK":
        return "[Mode: 🟡 Local Fallback Runbook]"
    return ""


def format_step_header(
    tool_name: str,
    duration_ms: float,
    source_mode: str | None = None,
    is_error: bool = False,
) -> str:
    """Format the header title of a tool execution step."""
    icon = TOOL_ICONS.get(tool_name, "🔧")
    badge = "[Read-Only]" if tool_name in READ_ONLY_TOOLS else "[Write-Gated]"
    mode_badge = get_mode_badge(source_mode)
    error_badge = " [⚠️ Tool Error - Self-Correcting]" if is_error else ""

    parts = [f"{icon} {tool_name}", f"• {badge}", f"• {int(duration_ms)}ms"]
    if mode_badge:
        parts.append(mode_badge)
    if error_badge:
        parts.append(error_badge)

    return " ".join(parts)


def format_approval_card(pending: Mapping[str, Any] | PendingRemediation) -> str:
    """Generate the Markdown presentation for the Human-in-the-Loop approval gate."""
    service_name = pending.get("service_name", "unknown")
    action_type = pending.get("action_type", "unknown")
    parameters = pending.get("parameters", {})
    idempotency_key = pending.get("idempotency_key", "")
    reason = str(pending.get("reason", "")).replace("|", "\\|").replace("\n", " ")

    params_json = json.dumps(parameters, indent=2, ensure_ascii=False)

    return f"""<div class="sre-approval-card">

### ⚠️ نیاز به تایید اپراتور (Human Approval Required)

> **هشدار ایمنی:** عامل هوشمند قصد اعمال تغییر در وضعیت زیرساخت را دارد.
> این عملیات در مرحله گیت نظارتی متوقف شده است. لطفاً جزئیات را بازبینی کرده و تصمیم بگیرید.

| مشخصه / فیلد | مقدار مشخصه |
| :--- | :--- |
| **سرویس هدف (Target Service)** | `{service_name}` |
| **نوع عملیات (Proposed Action)** | `{action_type}` |
| **کلید یکتایی (Idempotency Key)** | `{idempotency_key}` |
| **استناد و دلیل (Justification)** | {reason} |

<div class="sre-params-label">پارامترهای اجرایی (Parameters):</div>

```json
{params_json}
```

</div>"""


def format_welcome_message() -> str:
    """Return the bilingual command center banner and incident starters."""
    return """# ⚡ سامانه مدیریت و پاسخ به حوادث زیرساخت (OmniOps SRE Agent)

خوش آمدید. این کنسول هوشمند به سرور **Model Context Protocol (MCP)** متصل بوده
و حوادث را با گیت نظارتی **Human-in-the-Loop (HITL)** بررسی و رفع می‌کند.

---

### 🛡️ وضعیت عملیاتی سیستم:
- **پایگاه داده (PostgreSQL 16):** ✅ متصل (جداول عملیاتی و چک‌پوینت‌ها)
- **ابزارهای تشخیصی (MCP):** ✅ فعال (`get_service_health`, `query_incident_logs`,
  `search_runbooks`)
- **ابزار اعمال تغییر (Write Tool):** 🔒 تحت نظارت گیت انسانی (`execute_remediation`)
- **مدار شکن مستندات (Circuit Breaker):** 🟢 آماده (اتصال ران‌بوک‌های زنده / محلی)

---

### 🚀 سناریوهای آماده جهت بررسی:
برای شروع، می‌توانید یکی از درخواست‌های زیر را ارسال فرمایید:

1. `سرویس payment-api کند شده و کاربران خطای 502 می‌گیرند. بررسی کن.`
2. `کش redis-cache دچار افت کارایی شده و خطای OOM گزارش شده است. علت را ریشه‌یابی کن.`
3. `وضعیت سلامت کلی سرویس auth-service و postgres-primary را بررسی کن.`
"""


def format_remediation_summary(result: Mapping[str, Any], approval_status: str) -> str:
    """Format the post-remediation execution result."""
    if approval_status == "APPROVED":
        status_text = "✅ **عملیات با موفقیت تایید و اجرا شد (Remediation Executed)**"
        replay = (
            " (بازپخش کلید تکراری - Idempotent Replay)" if result.get("idempotent_replay") else ""
        )
        details = json.dumps(result, indent=2, ensure_ascii=False)
        return f"{status_text}{replay}\n\n```json\n{details}\n```"
    return f"""❌ **عملیات توسط اپراتور لغو گردید (Remediation Aborted by Operator)**

> **علت لغو:** {result.get("reason", "توسط کاربر رد شد.")}
"""
