# Testing & Agent Evaluation Strategy (TESTING.md)

## 1. Testing Philosophy
Testing an AI Agent system requires separating **deterministic software verification** from **stochastic model evaluation**:
1. **Tier 1: Model-Free Unit Tests (`tests/unit/`):** Exercise all 4 MCP tools, idempotency ledger, and the `OmniDoc RAG` circuit breaker directly in Python with **zero LLM calls** (< 3 seconds execution).
2. **Tier 2: Stateful Graph Integration Tests (`tests/integration/`):** Use a deterministic Mock LLM with pre-scripted tool calls to verify that LangGraph pauses at `interrupt_before=["remediation_node"]`, saves state in PostgreSQL, and resumes properly upon approval or rejection.
3. **Tier 3: Quantitative Agent Benchmark & Model Comparison (`evals/`):** Run 25 realistic incident scenarios against local vLLM comparing `Qwen2.5-1.5B-Instruct-AWQ` vs. `Qwen2.5-7B-Instruct-AWQ`.

---

## 2. Quantitative Agent Evaluation Metrics (`evals/run_agent_benchmark.py`)

Unlike Project 1 (which used Ragas for text retrieval), Project 2 evaluates **Agentic Behavior & Determinism**:

| Metric | Definition | Production Target (`7B-AWQ`) | CI Minimum Gate |
| :--- | :--- | :--- | :--- |
| **1. Tool Selection Accuracy** | Percentage of turns where the agent selects the exact optimal diagnostic/remediation tool sequence. | $\ge 92\%$ | $\ge 85\%$ |
| **2. Schema & Argument Validity** | Percentage of tool calls that pass Pydantic V2 validation on the first attempt without hallucinated parameters. | $\ge 96\%$ | $\ge 90\%$ |
| **3. Fault Recovery Rate** | When injected with a simulated error (`SERVICE_NOT_FOUND` or transient timeout), percentage of runs where the agent self-corrects on the next step. | $\ge 88\%$ | $\ge 80\%$ |
| **4. HITL Gate Safety Rate** | Percentage of write actions (`execute_remediation`) that halt at the approval checkpoint prior to execution. | $100\%$ | $100\%$ |
| **5. Idempotency Compliance** | Percentage of retried write actions that prevent duplicate state mutation. | $100\%$ | $100\%$ |

---

## 3. Model Size Comparison Experiment (`1.5B` vs. `7B`)
A core portfolio highlight of this repository is running `evals/run_agent_benchmark.py` across both model sizes on the exact same 16GB VRAM machine:
- Demonstrates why `Qwen2.5-1.5B-Instruct-AWQ` excelled at grounded summarization in Project 1, while `Qwen2.5-7B-Instruct-AWQ` provides a massive jump in multi-step JSON tool-calling determinism and self-correction in Project 2.

---

## 4. Test Commands
```bash
# Tier 1: Fast Unit Tests (No GPU / No LLM required)
pytest tests/unit -v

# Tier 2: Graph & API Integration Tests
pytest tests/integration -v

# Tier 3: Live Agent Evaluation Suite (Requires vLLM & Postgres)
python -m evals.run_agent_benchmark --model Qwen/Qwen2.5-7B-Instruct-AWQ --output evals/results/eval_7b.json
python -m evals.run_agent_benchmark --model Qwen/Qwen2.5-1.5B-Instruct-AWQ --output evals/results/eval_1_5b.json
```
