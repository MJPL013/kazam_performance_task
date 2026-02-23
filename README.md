# Performance Log Analysis Agent (Phase 2)

> An SRE agent that lets you interrogate microservice logs in plain English and get back structured, actionable diagnostics. Built on a ReAct loop using Gemini or any OpenAI-compatible LLM.

---

## Table of Contents

1. [Quick Start](#1-quick-start)
2. [Usage](#2-usage)
3. [Architecture](#3-architecture)
4. [Performance Thresholds & Detection Logic](#4-performance-thresholds--detection-logic)
5. [Limitations & Trade-offs](#5-limitations--trade-offs)
6. [Design Choices](#6-design-choices)
7. [Time Investment & Methodology](#7-time-investment--methodology)
8. [AI Assistance Used](#8-ai-assistance-used)

---

## 1. Quick Start

> **Prerequisite:** Python **3.13+** is required. Python 3.13 added native support for the `Z`-suffix in ISO 8601 timestamps (`2025-02-19T14:45:00Z`). Older versions cannot parse the `Z` shorthand with `fromisoformat()`, which is used throughout the log parser.

### Option A — Google Gemini

```bash
# 1. Clone and enter the project
git clone https://github.com/MJPL013/kazam_performance_task.git
cd kazam_performance_task

# 2. Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure credentials
copy .env.example .env
# Edit .env:
#   LLM_PROVIDER=gemini
#   GEMINI_API_KEY=your-key-here
#   GEMINI_MODEL=gemini-2.0-flash

# 5. Run the agent
python agent.py
```

### Option B — OpenAI / DeepSeek / any OpenAI-compatible API

```bash
# Same steps 1–3 as above, then:
# Edit .env:
#   LLM_PROVIDER=openai
#   OPENAI_API_KEY=your-key-here
#   OPENAI_BASE_URL=https://api.deepseek.com/v1   # or https://api.openai.com/v1
#   OPENAI_MODEL=deepseek-chat                    # or gpt-4o

python agent.py
```

### Verify without an API Key (smoke test)

```bash
python agent.py --smoke
# Expected: SMOKE TEST RESULTS: 8/8 passed
```

---

## 2. Usage

### Interactive Chat

```
python agent.py

You: Check payment_api for slow requests
[Agent calls detect_slow_requests → formats and responds]

You: Now diagnose where the latency is coming from
[Agent calls diagnose_latency_sources → breaks down DB / External API / App Logic]

You: exit
```

Arrow keys supported for history navigation. Type `exit` or `quit` to stop.

### Example Queries

```
# Slow request detection
"Show me API endpoints slower than 1 second in the last hour"
"Are there any slow requests in the charging controller?"

# Error analysis
"What's causing the spike in 5xx errors on payment_api?"
"Show me error patterns for charging_controller grouped by event_type"
"Which provider has more failures — twilio or sendgrid?"

# Resource / health monitoring
"Is the payment service having connection pool exhaustion?"
"Check the notification service queue status"
"Which charging stations are experiencing the most hardware errors?"

# Deep-dive / root cause
"Find slow requests in payment_api then diagnose where the latency is coming from"
"Is payment_api performance getting worse compared to the baseline?"
"Check if STATION_042 has hardware errors"
```

See `demo/example_queries.txt` for the full list.

### Tool Parameters Reference

| Parameter | Default | Notes |
|-----------|---------|-------|
| `service` | `None` (all services) | `"payment_api"`, `"charging_controller"`, `"notification_service"` |
| `time_window` | `"1h"` | Accepts `"30m"`, `"6h"`, `"24h"`, `"48h"` |
| `threshold_ms` | `2000` | Latency cutoff for slow request detection |
| `group_by` | `"endpoint"` | Also `"error_type"`, `"provider"` |
| `baseline_window` | `"24h"` | Historical window for latency comparison (disjoint from current) |
| `endpoint` | `None` | Filter `diagnose_latency_sources` to a specific endpoint |

---

## 3. Architecture

### Project Structure

```
Phase2/
├── agent.py                    # Orchestrator: ReAct loop, provider adapters, CLI
├── requirements.txt
├── .env.example
│
├── tools/
│   ├── __init__.py
│   ├── latency_analysis.py     # detect_slow_requests, diagnose_latency_sources
│   ├── error_analysis.py       # analyze_error_patterns
│   └── resource_monitoring.py  # check_resource_usage
│
├── utils/
│   ├── __init__.py
│   ├── log_parser.py           # LogEntry (Pydantic), LogStore (bisect filtering)
│   └── baseline_calculator.py  # severity_label, percentile, median, parse_window
│
├── prompts/
│   └── system_prompt.txt       # Agent persona, tool rules, output format spec
│
├── logs/
│   ├── payment_api.log
│   ├── charging_controller.log
│   └── notification_service.log
│
├── demo/
│   └── example_queries.txt
│
└── tests/
    ├── test_tools.py           # 13 tests: tool contracts, edge cases, data_context
    └── test_agent.py           # 5 tests: orchestration, history truncation, execute_tool
```

### Data Flow

```
User (natural language)
        │
        ▼
 SREAgent.chat()
        │  ┌─ appends to conversation_history
        │  └─ sliding-window truncation (MAX_HISTORY_MESSAGES)
        │
        ▼
 LLM Provider (Gemini / OpenAI-compatible)
        │  Receives system prompt + conversation history
        │  Returns: text OR tool call JSON
        │
        ▼
 execute_tool(name, args)
        │  ┌─ LogStore.filter(service, time_window, ...)
        │  │     └─ bisect on sorted timestamp list → O(log n) slice
        │  │     └─ linear scan on already-narrowed subset
        │  │
        │  ├─ detect_slow_requests()      → profiles, spike_windows, top_slow_requests
        │  ├─ diagnose_latency_sources()  → breakdowns, baseline comparison, coverage_warning
        │  ├─ analyze_error_patterns()    → buckets (error types + failure rates), stress_signals
        │  └─ check_resource_usage()      → indicators with severity per service
        │
        │  All tools return structured dicts (not strings)
        │  Result is JSON-serialised and fed back into conversation_history
        │
        ▼
 LLM synthesises tool output into markdown response
        │
        ▼
 User (formatted SRE diagnosis)
```

### Tool Descriptions

**`detect_slow_requests(store, service, threshold_ms, time_window)`**
Filters all log entries in the time window to those with `effective_response_time_ms >= threshold_ms`. Fast failures (HTTP status ≥ 400 AND response time < 100 ms) are excluded from baseline pool calculations because they represent rejected requests at the load balancer, not real latency. Results are grouped by endpoint to produce P50/P90/Max profiles, then a spike detector scans for windows where 3 or more slow requests cluster within 5 minutes. The top 10 slowest requests are returned with their full latency breakdowns.

**`diagnose_latency_sources(store, service, endpoint, time_window, baseline_window)`**
Decomposes response time into four components — DB query time, External API time, App logic time, and Unaccounted (total minus known components). The current window and baseline window are explicitly disjoint: baseline ends where the current window begins, so the same requests cannot appear in both pools. Per-endpoint median is computed for each component. The primary bottleneck is the component with the largest share of total median latency. A coverage warning is emitted when more than 5% of requests are missing timing fields.

**`analyze_error_patterns(store, service, time_window, group_by)`**
Counts errors grouped by endpoint, error_type, or provider (for notification_service). The failure rate denominator uses only request-count entries — lifecycle events like `session_started` or `notification_queued` are excluded to avoid inflating the denominator. Client errors (4xx) and server errors (5xx) are tallied separately. WARN-level events are surfaced as stress signals independently of the error buckets, because they often precede outages.

**`check_resource_usage(store, service, time_window)`**
Because these are application logs without OS-level telemetry, resource health is inferred from log-signal proxies. For `payment_api`: strict error rate (ERROR/5xx only), warn/throttle rate, DB connection pool exhaustion events (distinct from normal slow queries), and external API gateway timeouts. For `charging_controller`: hardware communication errors per station, abnormal state transitions, session completion ratio. For `notification_service`: queue depth (highest observed backlog in window), retry exhaustion count, and delivery failure rate split by provider (twilio vs. sendgrid). Each indicator is labelled NORMAL / MEDIUM / HIGH / CRITICAL.

### Agent Orchestration

`agent.py` implements a ReAct (Reason → Act → Observe) loop:

1. User input is appended to `conversation_history`.
2. History is sent to the provider (Gemini or OpenAI-compatible) along with the system prompt.
3. If the LLM returns a tool call, `execute_tool()` is dispatched, and the JSON result is injected back into history as a tool response.
4. Steps 2–3 repeat until the LLM returns a plain text response (no more tool calls).
5. History is truncated with a sliding window (`MAX_HISTORY_MESSAGES = 20`) when it grows too large, always preserving the leading user message after trimming.

Two provider adapters share the same interface (`chat(history, system_prompt) → (text, tool_log)`):
- **`GeminiProvider`** — uses `google-genai` SDK with native function-calling support
- **`OpenAIProvider`** — uses the `openai` library, compatible with DeepSeek, local Ollama endpoints, etc.

---

## 4. Performance Thresholds & Detection Logic

### Severity Labels

Severity is expressed as a ratio of the current metric to its baseline:

| Severity | Multiplier | Operational Meaning |
|----------|-----------|---------------------|
| **CRITICAL** | ≥ 10× baseline | SLA breach almost certain; page on-call immediately |
| **HIGH** | ≥ 5× baseline | Degradation visible to users; investigate within minutes |
| **MEDIUM** | ≥ 2× baseline | Anomalous but not yet user-impacting; monitor and alert |
| **NORMAL** | < 2× baseline | Within acceptable variance |

These ratios are applied in `baseline_calculator.py:severity_label()`.

### Default Latency Thresholds

| Service | Default Threshold | Rationale |
|---------|------------------|-----------|
| `payment_api` | 500 ms (recommended) | Payments are latency-sensitive; 2 s is too lenient |
| `charging_controller` | 2000 ms | Hardware I/O is slower; 2 s is acceptable |
| `notification_service` | 5000 ms | Async delivery queue; latency tolerance is higher |

The agent's system prompt advises the LLM to lower to 500 ms for `payment_api` and raise to 5000 ms for `notification_service` when relevant.

### Fast Failure Exclusion

A request with HTTP status ≥ 400 **and** response time < 100 ms is classified as a fast failure (`LogEntry.is_fast_failure`). These are excluded from the latency baseline pool in `detect_slow_requests` because they represent requests rejected at the load balancer or API gateway before touching application logic — including them would deflate the baseline and cause normal requests to appear artificially slow.

5xx errors with response time ≥ 100 ms are always included: the server processed them and the latency is real.

### Disjoint Baseline Windows

`diagnose_latency_sources` enforces strictly non-overlapping time windows:

```
baseline_window (e.g., 48h) = [T - 72h  →  T - 24h]
current_window  (e.g., 24h) = [T - 24h  →  T     ]
                                              ▲
                              Baseline ends exactly where current starts
```

If both windows included the same requests, any improvement or degradation could be hidden. The disjoint constraint ensures the baseline reflects a genuinely historical period.

### Error Rate Denominator

The error rate is computed as:

```
failure_rate_pct = errors_in_group / request_entries_in_window * 100
```

`request_entries_in_window` counts only entries that represent HTTP requests (those with an `endpoint` field). Lifecycle events (`session_started`, `session_completed`, `notification_queued`, etc.) are excluded. This matters because `charging_controller` and `notification_service` emit many non-request events, and mixing them into the denominator would produce misleadingly low error rates.

---

## 5. Limitations & Trade-offs

### What This Agent Cannot Do

**Session Duration Drift (charging_controller)**
Charging session durations cannot be computed. `session_started` events do not include a `user_id`, and `session_completed` events do not include a `connector_id`. There is no shared key to join the two event types. The `check_resource_usage` indicator for session duration drift explicitly returns `unavailable`.

**Static Logs Only**
The agent processes a fixed log snapshot loaded at startup via `LogStore`. There is no tail/streaming or inotify integration. If you restart the agent with a fresh log file, it will re-parse from scratch.

**`charging_session_timeout` Duration Bucketing Not Implemented**
The logs contain `charging_session_timeout` events, but there is no bucket analysis (e.g., P50/P90 of timeout durations by station). Only the count is surfaced.

**Resource Proxies, Not Real Metrics**
`check_resource_usage` infers resource health from application log signals — it does not read CPU usage, memory RSS, file descriptor counts, or network I/O from any OS or APM API. Connection pool exhaustion is detected by counting `db_connection_pool_exhausted` log events, not by querying the pool itself.

**No Real-Time Clock Alignment**
`reference_time` is derived from the latest log entry timestamp, not `datetime.now()`. All time windows are relative to `reference_time`. If the logs are older than the current time (they are — the sample data ends in February 2025), the agent warns the user that the data is historical.

**Single-Process, No Concurrency**
The agent handles one conversation at a time. There is no multi-user session support or request queuing.

**History Truncation Drops Context**
With `MAX_HISTORY_MESSAGES = 20`, very long conversations will lose early context. If a user references a finding from 15 turns ago, the agent may not recall it.

---

## 6. Design Choices

**No LangChain or LLM frameworks.** The entire orchestration is ~200 lines of plain Python. This keeps the call stack debuggable and makes it straightforward to reason about what the model is receiving at each step.

**Pydantic v2 for log parsing.** Pydantic's `model_validator` and `extra="allow"` let the same `LogEntry` model absorb all three services' schemas without separate parsers. The `effective_response_time_ms` property normalises the three different field names used across services into a single accessor.

**Structured dict outputs from tools, not strings.** Tools return Python dicts that are JSON-serialised before being fed back to the LLM. This lets the model reason about specific field values (e.g., `"bottleneck_pct": 71.3`) rather than parsing its own earlier text output.

**Bisect-based time filtering.** `LogStore` maintains a sorted list of timestamps alongside the entry list. `bisect_left`/`bisect_right` on the timestamps gives O(log n) slicing; the actual entry extraction is then a single list slice. Service-indexed maps give O(1) service lookups before the time filter is applied.

**`data_context` in every tool response.** Every tool returns a `data_context` block with `log_data_ends_at`, `hours_since_last_log`, and `is_historical`. The system prompt instructs the LLM to surface a staleness warning to the user whenever `is_historical` is true. This prevents stale data from being presented as real-time.

---

## 7. Time Investment & Methodology

**Total: ~12 hours**

### Phase 0 — Exploratory Data Analysis (1 hour)
Started with raw EDA on the three log files: counted entries per service, enumerated all unique `event_type` values, mapped which fields were present across services, and identified the three-way schema divergence for response time fields (`response_time_ms` at root level for `payment_api`, `metadata.response_time_ms` for `charging_controller`, `metadata.processing_time_ms` for `notification_service`). Also confirmed that `session_started` and `session_completed` lack a shared join key, which immediately ruled out session duration analysis.

### Phase 1 — Core Engine in Pure Python (3 hours)
Built the deterministic data-processing engine with no LLM dependency: `LogEntry` Pydantic model, `PerformanceAnalyzer` class with all four tool methods, and a 61-test harness. The engine returns SRE-formatted string reports. This phase was treated as a standalone unit: the goal was to make every analytical decision explicit and testable before adding LLM complexity on top.

### Phase 1.1 — Production Refactor (4 hours)
Refactored the Phase 1 engine for Phase 2 integration:
- Replaced raw lists with `LogStore` (Pydantic parsing + bisect indexing)
- Changed tool return type from string reports to structured dicts for LLM consumption
- Introduced `baseline_calculator.py` as a shared math module
- Fixed multiple bugs found during this refactor (see AI Assistance section)

### Phase 2 — Agent Wrapper & Multi-LLM Evaluation (3 hours)
Wrapped the engine in a ReAct orchestrator. Wrote provider adapters for Gemini and OpenAI-compatible APIs. Evaluated agent output quality across three models (Gemini 2.0 Flash, DeepSeek Chat, GPT-4o). All three models correctly triggered multi-tool chains when asked root-cause questions. Key observation: models differed mainly in how they formatted markdown tables and whether they proactively flagged `data_context.is_historical` warnings. Refined the system prompt based on this evaluation — added explicit formatting rules and the `AMBIGUITY FALLBACK` rule after observing that two of three models would loop on vague service queries.

### Documentation (1 hour)
This README.

---

## 8. AI Assistance Used

AI was used throughout this project for architecture planning, code generation, and — most significantly — iterative bug detection.

**Where AI helped:**
- Initial architecture design (provider adapter pattern, bisect indexing strategy, Pydantic model shape)
- First-pass implementations of all four tool functions and both provider adapters
- System prompt structure and the AMBIGUITY FALLBACK rule

**Bugs found through iterative AI-assisted review (5 rounds, 8+ logic errors):**

| Bug | Impact Before Fix |
|-----|-------------------|
| WARN events counted in both error buckets AND stress signals | WARN-level error rate was double-counted |
| Fast failures included in baseline latency pool | Baseline median was pulled down by ~30ms |
| `session_started` / `session_completed` join attempted on mismatched keys | Duration calculation silently returned 0 for all sessions |
| Error rate denominator included lifecycle events | Effective error rate for `charging_controller` was ~6× lower than real |
| Spike detector used inclusive windows (3-req clusters could span 10 min) | Some non-spikes were classified as spikes |
| `diagnose_latency_sources` baseline window overlapped with current window | Degradations appeared smaller than they were |
| `group_key` fallback to `event_type` not applied consistently | ~15% of `notification_service` entries were dropped from error analysis |
| SEVERITY_THRESHOLDS iteration order not guaranteed (Python dict) | CRITICAL threshold was sometimes evaluated after HIGH, returning wrong label |

**What AI got wrong on first pass:**
- Used `datetime.now()` as `reference_time` instead of deriving it from the latest log timestamp, making analysis non-deterministic and time-dependent
- Applied the WARN overcounting in stress signal generation (double-counted as both error and stress)
- Initial severity thresholds were 3×/2×/1.5× (too sensitive for SRE operational context; corrected to 10×/5×/2×)
- Generated coverage warning at 0% missing data instead of only when coverage gap > 5%

All bugs were caught through explicit test assertions and code review, not just by running the agent and observing bad output.

---

## Dependencies

```
pydantic>=2.0          # Log parsing and validation
google-genai>=1.0      # Gemini provider
openai>=1.0            # OpenAI-compatible provider
python-dotenv>=1.0     # .env loading
colorama>=0.4          # Terminal colour output
```

No APM platform SDKs. No LangChain. No vector databases.

---

## Running Tests

```bash
# Unit tests (18 tests — tool contracts + agent orchestration)
python -m unittest tests.test_tools tests.test_agent -v

# Smoke tests (8 tests — all 4 tools against real log files)
python agent.py --smoke
```
