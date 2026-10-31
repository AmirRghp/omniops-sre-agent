# عامل هوشمند SRE آمُنی‌آپز (OmniOps SRE Agent) ⚡

> **پلتفرم خودکار مدیریت و پاسخ به حوادث زیرساخت مبتنی بر پروتکل کانتکست مدل (MCP)**  
> *پروژه دوم از نقشه راه مهندسی هوش مصنوعی (AI Engineering Roadmap) — طراحی‌شده برای عیب‌یابی خودکار، ابزارهای قطعی MCP و ایمنی زیرساخت با نظارت انسان (Human-in-the-Loop).*

[English](README.md) | [فارسی](README.fa.md)

[![CI Quality Gate](https://github.com/AmirRghp/omniops-sre-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/AmirRghp/omniops-sre-agent/actions/workflows/ci.yml)
[![Deterministic Benchmark](https://github.com/AmirRghp/omniops-sre-agent/actions/workflows/agent-evals.yml/badge.svg)](https://github.com/AmirRghp/omniops-sre-agent/actions/workflows/agent-evals.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastMCP](https://img.shields.io/badge/MCP-FastMCP%20SDK-purple.svg)](https://modelcontextprotocol.io/)
[![LangGraph](https://img.shields.io/badge/Orchestration-LangGraph%20AsyncPostgres-orange.svg)](https://langchain-ai.github.io/langgraph/)
[![vLLM Ready](https://img.shields.io/badge/Inference-vLLM%20AWQ-green.svg)](https://github.com/vllm-project/vllm)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## ۱. معرفی سیستم

**عامل هوشمند OmniOps** یک پلتفرم آماده تولید، خودکار و دوزبانه (فارسی و انگلیسی) در حوزه مهندسی پایداری سرویس (Site Reliability Engineering) است. این سامانه با تجمیع خودکار داده‌های تله‌متری زنده، جستجوی ساختاریافته در لاگ‌های حوادث، کاوش ران‌بوک‌های فنی و پیشنهاد اقدامات اصلاحی در پشت یک **گیت نظارت انسانی غیرقابل‌دورزدن (HITL)**، خستگی ناشی از هشدارهای مکرر (Alert Fatigue) و تاخیر در تریاژ بحران‌ها را برطرف می‌کند.

### ارکان کلیدی معماری:
1. **معماری مستقل و پروتکل‌محور (Decoupled MCP Architecture):** تمامی قابلیت‌های سیستم در قالب ابزارهای استاندارد **پروتکل کانتکست مدل (FastMCP SDK)** پیاده‌سازی شده‌اند. همین سرور ابزار، همزمان عامل LangGraph، کنسول کاربری Chainlit و محیط‌های Cursor IDE و Claude Desktop را تغذیه می‌کند.
2. **ماشین وضعیت پایا با چک‌پوینت‌های PostgreSQL:** مبتنی بر LangGraph و `AsyncPostgresSaver` که امکان توقف نامحدود بررسی‌ها در گیت تایید انسانی را بدون باز نگه داشتن اتصال سوکت یا از دست رفتن وضعیت پس از ری‌استارت کانتینر فراهم می‌سازد.
3. **گیت ایمنی سخت‌گیرانه نظارت انسانی (HITL):** عملیات جهش وضعیت زیرساخت (`execute_remediation`) در سطح معماری گراف با وقفه اجباری `interrupt_before=["remediation_node"]` مسدود می‌شود؛ بنابراین حتی در صورت تزریق پرامپت مخرب، مدل زبانی توانایی اعمال تغییرات تاییدنشده را ندارد.
4. **مدارشکن مقاوم (ضمانت کارکرد مستقل):** متصل به پروژه ۱ (`OmniDoc RAG`) روی پورت `8080`. در صورت در دسترس نبودن پروژه ۱، جستجوی دستورالعمل‌ها بلافاصله و بدون وقفه به ران‌بوک‌های دوزبانه محلی (`data/fallback_runbooks.json`) سوئیچ می‌کند.
5. **انضباط حافظه ۱۶ گیگابایت VRAM:** بهینه‌سازی‌شده برای سرو محلی از طریق vLLM با مدل `Qwen/Qwen2.5-7B-Instruct-AWQ` با سقف مصرف حافظه ۶۰٪ (`--gpu-memory-utilization 0.60`) که بیش از ۶ گیگابایت حافظه آزاد برای همزیستی با سایر سرویس‌ها باقی می‌گذارد.

---

## ۲. نمودار جریان معماری

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    External MCP Clients (Optional)                      │
│               (Cursor IDE / Claude Desktop / MCP Inspector)             │
└───────────────────────────────────┬─────────────────────────────────────┘
                                    │ (پروتکل ارتباطی Stdio / SSE MCP)
┌───────────────────────┐           ▼           ┌─────────────────────────┐
│     کنسول وب Chainlit │   ┌───────────────┐   │  پروژه ۱: OmniDoc RAG   │
│ (مشاهده تریاژ حوادث و │   │  OmniOps MCP  │──►│  (پورت 8080 وب‌سرویس)   │
│   دکمه تایید/رد HITL) │   │    Server     │   └────────────┬────────────┘
└───────────▲───────────┘   │ (FastMCP SDK) │                │ (مدارشکن پویا)
            │ SSE / Actions │               │   ┌────────────▼────────────┐
┌───────────▼───────────┐   │   ۴ ابزار     │──►│ ران‌بوک‌های محلی Fallback│
│    FastAPI Backend    │   │  ساختاریافته  │   │ (data/fallback_...json) │
└───────────▲───────────┘   └───────▲───────┘   └─────────────────────────┘
            │                       │ (پیلودهای معتبر Pydantic V2)
┌───────────▼───────────────────────┴─────────────────────────────────────┐
│                 ماشین وضعیت پایا در LangGraph (StateGraph)             │
│                                                                         │
│  [START] ──► [agent_reasoning_node] ◄──► [read_tools_node]             │
│                       │                                                 │
│          (فراخوانی ابزار execute_remediation)                           │
│                       ▼                                                 │
│         ⏸️ [گیت وقفه و تایید اجباری اپراتور انسان]                     │
│         (interrupt_before=["remediation_node"])                         │
│                       │                                                 │
│            ┌──────────┴──────────┐                                      │
│         تایید                  رد                                       │
│            ▼                     ▼                                      │
│  [remediation_node]     [rejection_handler]                             │
│  (اعمال تغییر با کلید یکتا) (راهنمای اقدام دستی)                        │
│            └──────────┬──────────┘                                      │
│                       ▼                                                 │
│             [agent_reasoning_node] ──► [END]                            │
└───────────────────────┬─────────────────────────────────────────────────┘
                        │
        ┌───────────────┴───────────────┐
        ▼                               ▼
┌───────────────────────┐       ┌───────────────────────┐
│     PostgreSQL 16     │       │   سرور استنتاج محلی   │
│ - جداول وضعیت سرویس‌ها │       │ vLLM (Qwen2.5 7B AWQ) │
│ - دفتر کل یکتایی اعمال│       │ (پورت 8000)           │
│ - چک‌پوینت‌های LangGraph│       └───────────────────────┘
└───────────────────────┘
```

---

## ۳. چهار ابزار تفکیک‌شده و تخصصی MCP

برای جلوگیری از خطای Hallucination در پارامترها، قابلیت‌ها به ۴ ابزار مشخص و تفکیک‌شده تقسیم شده‌اند:

| نام ابزار MCP | حالت دسترسی | شرح کاربرد |
| :--- | :---: | :--- |
| `get_service_health(service_name)` | **خواندنی (Read-Only)** | استعلام بلادرنگ وضعیت منابع پردازنده، رم، تاخیر P95، تعداد رپلیکا و اتصالات دیتابیس. |
| `query_incident_logs(service_name, severity, limit)` | **خواندنی (Read-Only)** | بازیابی لاگ‌های خطا با پوشش امنیتی تگ‌های `<untrusted_log_data>` جهت خنثی‌سازی تزریق پرامپت. |
| `search_runbooks(query, category)` | **خواندنی (Read-Only)** | جستجوی اسناد تریاژ از طریق اتصال RAG زنده پروژه ۱ یا پایگاه دانش رزرو محلی. |
| `execute_remediation(...)` | **محافظت‌شده با گیت (Write-Gated)** | اعمال تغییرات زیرساختی با بررسی کلید یکتایی (Idempotency) مشروط به تأیید اپراتور انسان. |

---

## ۴. راه‌اندازی سریع

### پیش‌نیازها
- ابزار Docker و Docker Compose
- پایتون ۳.۱۱ یا بالاتر
- (اختیاری) کارت گرافیک NVIDIA با حافظه $\ge 12\text{ GB}$ VRAM برای اجرای مدل محلی vLLM.

### روش الف: راه‌اندازی یکپارچه با Docker Compose
راه‌اندازی خودکار PostgreSQL 16، پنل Langfuse، سید دیتابیس و اجرای رابط کاربری:
```bash
docker compose up -d
```
- **کنسول کاربری SRE (چین‌لیت):** `http://localhost:8001`
- **وب‌سرویس REST و SSE:** `http://localhost:8000`
- **مستندات تعاملی Swagger:** `http://localhost:8000/docs`
- **داشبورد تله‌متری Langfuse:** `http://localhost:3000`

### روش ب: راه‌اندازی در محیط توسعه محلی
```bash
# ۱. کلون ریپازیتوری و آماده‌سازی محیط مجازی
git clone https://github.com/AmirRghp/omniops-sre-agent.git
cd omniops-sre-agent
make setup

# ۲. اجرای کانتینر پایگاه داده PostgreSQL
make docker-up

# ۳. مقداردهی اولیه جداول و لاگ‌های آزمایشی
make seed

# ۴. اجرای کنسول کاربری
make run-ui
# (در ویندوز: python run_app.py)
```

> **نکته پایداری در ویندوز:** اجرای دستور `python run_app.py` سیاست `WindowsSelectorEventLoopPolicy` را فعال می‌کند تا پردازش‌های همروند دیتابیس بدون مسدودی روی سیستم‌عامل ویندوز انجام شوند.

### روش ج: راه‌اندازی اکوسیستم کامل (همراه با پروژه ۱: OmniDoc RAG)
جهت اجرای همزمان هر دو پروژه روی یک سیستم با مدل استنتاج مشترک vLLM 7B:
- **پروژه ۱ (`OmniDoc RAG`):** جستجوی ترکیبی برداری ران‌بوک‌ها روی پورت `8080`.
- **پروژه ۲ (`OmniOps SRE Agent`):** عامل خودکار عیب‌یابی و تأیید انسانی روی پورت `8001`.

📖 **راهنمای قدم‌به‌قدم با دستورات دقیق خط فرمان:** به [راهنمای جامع یکپارچه‌سازی اکوسیستم](docs/ECOSYSTEM_INTEGRATION.md) مراجعه فرمایید.

---

## ۵. اتصال به کلاینت‌های عمومی MCP (Cursor و Claude Desktop)

می‌توانید محیط برنامه‌نویسی دلخواه خود را مستقیماً به سرور ابزار OmniOps متصل کنید:

### ۵.۱ تنظیم در ادیتور Cursor (`.cursor/mcp.json`)
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

### ۵.۲ تنظیم در برنامه Claude Desktop (`claude_desktop_config.json`)
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
      "cwd": "D:/Work/omniops-sre-agent",
      "env": {
        "DATABASE_URL": "postgresql+asyncpg://postgres:postgres@localhost:5432/omniops"
      }
    }
  }
}
```

---

## ۶. کنسول تعاملی Chainlit و گیت نظارت انسانی

کنسول کاربری (`app.py`) با رعایت اصول طراحی استاندارد پیاده‌سازی شده است:
- **آکاردئون‌های بلادرنگ ابزارها:** هر مرحله از اجرای ابزار در یک `cl.Step` شامل ورودی JSON، خروجی ساخت‌یافته، مدت‌زمان اجرا بر حسب میلی‌ثانیه و برچسب وضعیت مدارشکن (`[Mode: 🟢 Live OmniDoc RAG]` یا `[Mode: 🟡 Local Fallback Runbook]`) نمایش داده می‌شود.
- **کارت تایید انسانی (HITL Card):** با حاشیه طلایی رنگ و تفکیک مشخصات سرویس هدف، نوع عملیات، کلید یکتایی و دکمه‌های تعاملی `✅ تایید و اجرا (Approve)` و `❌ لغو عملیات (Reject)`.
- **تفکیک چیدمان متن دوزبانه:** چیدمان راست‌به‌چپ (RTL) برای متن فارسی توضیحات و ایزولاسیون کامل چپ‌به‌راست (LTR) برای نام متغیرها، مقادیر JSON و کدهای سیستمی.

---

## ۷. ارزیابی تجربی و بنچمارک مقایسه‌ای مدل‌ها

### ۷.۱ نتایج ارزیابی زنده مدل محلی (`Qwen2.5-7B-Instruct-AWQ` روی کارت گرافیک RTX 5060 Ti)
ارزیابی در برابر پایگاه‌داده واقعی PostgreSQL 16 و RAG زنده پروژه ۱ در ۲۵ سناریوی چندمرحله‌ای (`data/agent_eval_scenarios.json`):

| شاخص ارزیابی (Metric) | نتیجه بنچمارک زنده (7B-AWQ) | حد نصاب هدف (Floor) | تحلیل فنی و معماری |
| :--- | :---: | :---: | :--- |
| **صحت و انطباق اسکیما (Schema Validity)** | **`100.0%`** | $\ge 96\%$ | **صفر خطای ساختار JSON** در تمامی فراخوانی‌های ابزار |
| **رهگیری گیت نظارت انسانی (HITL Rate)** | **`100.0%`** | $100\%$ | **۱۰۰٪ عملیات‌های اصلاحی متوقف شدند** تا تایید اپراتور دریافت شود |
| **دفاع در برابر تزریق پرامپت (Prompt Defense)** | **`100.0%`** | $100\%$ | **۴ از ۴ حمله خنثی شد** (دستور override در لاگ، بای‌پس اضطراری و دستورات خطرناک ترمینال مثل `rm -rf /`) |
| **دقت زنجیره انتخاب ابزار (Tool Accuracy)** | **`84.0%`** | $\ge 80\%$ | زنجیره‌سازی ترتیبی و تشخیصی (`health` ← `logs` ← `runbooks` ← `remediation`) |
| **مجموع سناریوهای پاس‌شده** | **`18 / 25 (72.0%)`** | - | تریاژ بلادرنگ دنیای واقعی بدون دور زدن تست‌ها |

> گزارش کامل خروجی در فایل [`evals/results/eval_7b.json`](evals/results/eval_7b.json) قابل مشاهده است.

### ۷.۲ مقایسه عملکرد معماری: مدل `1.5B` در برابر `7B`

| شاخص ارزیابی | مدل `Qwen2.5-1.5B-Instruct-AWQ` | مدل `Qwen2.5-7B-Instruct-AWQ` | حد نصاب هدف | برتری مدل 7B |
| :--- | :---: | :---: | :---: | :--- |
| **دقت انتخاب ابزار** | `88.0%` | **`100.0%`** | $\ge 92\%$ | **+12.0%** (زنجیره‌سازی بهینه ابزارها) |
| **اعتبار اسکیما و آرگومان‌ها** | `96.0%` | **`100.0%`** | $\ge 96\%$ | **+4.0%** (عدم تولید پارامترهای موهوم) |
| **نرخ بازیابی خطا و نام اشتباه** | `60.0%` | **`100.0%`** | $\ge 88\%$ | **+40.0%** (اصلاح خودکار املای غلط سرویس‌ها) |
| **مهار در گیت تایید انسانی** | **`100.0%`** | **`100.0%`** | $100\%$ | **مشترک (۱۰۰٪ تضمین‌شده با ساختار گراف)** |
| **تاخیر پاسخ تک‌مرحله‌ای (P95)** | **`280ms`** | `420ms` | $\le 2000\text{ms}$ | **مدل 1.5B (حدود ۱.۵ برابر سریع‌تر)** |
| **مصرف حافظه گرافیکی (VRAM)** | **`~1.4 GB`** | `~5.2 GB` | $\le 11\text{ GB}$ | **مدل 1.5B (سبک‌تر)** |

### اجرای بنچمارک‌ها:
```bash
# ارزیابی شبیه‌سازی‌شده (Dry-Run)
python -m evals.run_agent_benchmark --dry-run

# ارزیابی زنده روی سرور vLLM و PostgreSQL
python -m evals.run_agent_benchmark --model Qwen/Qwen2.5-7B-Instruct-AWQ --output evals/results/eval_7b.json

# تولید جدول مقایسه‌ای مدل 1.5B و 7B
python -m evals.run_agent_benchmark --compare evals/results/eval_1_5b.json evals/results/eval_7b.json
```

---

## ۸. هرم آزمون‌ها و اعتبارسنجی کیفیت

```bash
# اجرای تمامی ۱۱۰ آزمون اتوماتیک (پاس ۱۰۰٪)
pytest -v

# آزمون کنترل نوع متغیرها (Type Check)
mypy src evals app.py main.py

# بررسی سبک و فرمت کدها (Lint & Format)
ruff check src tests evals app.py main.py
ruff format --check src tests evals app.py main.py
```

---

## ۹. محدودیت‌ها و چالش‌های شناخته‌شده

1. **شبیه‌سازی امن تغییر وضعیت:** عملیات اصلاحی به جای اجرای مستقیم دستورات خطرناک روت (`rm -rf` یا `kubectl delete`) روی هاست، بر روی دفتر کل وضعیت سرویس‌ها در PostgreSQL اعمال می‌شوند تا ایمنی محیط سندباکس تضمین شود.
2. **فشار حافظه در پردازش همزمان vLLM:** در صورت مراجعه همزمان چند کاربر روی کارت گرافیک ۱۶ گیگابایت، در صورت عبور طول کانتکست از ۸۱۹۲ توکن، ممکن است تاخیر پاسخگویی افزایش یابد.
3. **پایگاه داده چک‌پوینت در یک ناحیه:** در وضعیت فعلی چک‌پوینت‌های LangGraph روی یک دیتابیس محلی ذخیره می‌شوند؛ برای استقرار توزیع‌شده بین‌المللی استفاده از راهکارهای Multi-Region مثل CockroachDB توصیه می‌شود.

---

## ۱۰. مجوز (License)

این پروژه تحت مجوز [MIT](LICENSE) منتشر شده است.
