# Performance Log Analysis Agent

A production-grade AI agent that lets SRE/DevOps engineers query microservice logs using natural language to diagnose performance bottlenecks, track error patterns, and monitor resource health across three services: **payment_api**, **charging_controller**, and **notification_service**.

---

## Quick Start

### Prerequisites
- **Python 3.13+** (required for native ISO 8601 `Z`-suffix parsing)
- An LLM API key (Google Gemini **or** any OpenAI-compatible provider)

### Setup (~3 minutes)

```bash
# 1. Clone & enter the project
git clone https://github.com/MJPL013/kazam_performance_task.git
cd kazam_performance_task

# 2. Create virtual environment
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS/Linux
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure your LLM provider
cp .env.example .env
# Edit .env with your API key (see Configuration section below)

# 5. Run the agent
python agent.py
```

### Configuration

Edit `.env` to select your LLM provider:

**Option A: Google Gemini (recommended)**
```env
LLM_PROVIDER=gemini
GEMINI_API_KEY=your-api-key-here
GEMINI_MODEL=gemini-2.0-flash
```

**Option B: OpenAI-compatible API (DeepSeek, ZLM, local models)**
```env
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-your-key-here
OPENAI_BASE_URL=https://api.deepseek.com/v1
OPENAI_MODEL=deepseek-chat
```

---

## Usage

### Interactive Mode

```bash
python agent.py
```

The agent starts a REPL. Type natural language queries:

```
You: What's the slowest endpoint right now?
You: Show me error patterns for the charging controller
You: Why is /api/v1/payments/process slow?
You: Is any service having resource issues?
```

Type `exit` or `quit` to end the session.

### Smoke Test

Verifies all 4 tools execute without errors and return valid output:

```bash
python agent.py --smoke
```

### Example Queries

| Category | Example Query |
|----------|---------------|
| **Performance** | "Show me API endpoints slower than 2 seconds in the last hour" |
| **Error Analysis** | "What's causing the spike in 5xx errors?" |
| **Resource Health** | "Is the payment service having memory issues?" |
| **Root Cause** | "Why is /api/v1/payments/process so slow right now?" |
| **Comparison** | "Compare response times: this hour vs. last hour" |
| **Multi-step** | "Find slow requests, then check if they're hitting database timeouts" |

---

## Architecture

```
agent.py                         ← ReAct loop orchestrator (Gemini + OpenAI)
│
├── prompts/system_prompt.txt    ← SRE persona + tool-use rules
│
├── tools/
│   ├── latency_analysis.py      ← Tool 1: detect_slow_requests
│   │                              Tool 2: diagnose_latency_sources
│   ├── error_analysis.py        ← Tool 3: analyze_error_patterns
│   └── resource_monitoring.py   ← Tool 4: check_resource_usage
│
├── utils/
│   ├── log_parser.py            ← Pydantic LogEntry model + LogStore (bisect-optimised)
│   └── baseline_calculator.py   ← Severity logic, percentile, median, window parsing
│
└── logs/                        ← Sample log files (JSON Lines)
    ├── payment_api.log          (~1200 entries)
    ├── charging_controller.log  (~1000 entries)
    └── notification_service.log (~800 entries)
```

### Data Flow

```
User Query → LLM (Gemini/OpenAI) → Tool Selection → Tool Function
                                                          │
                                                    LogStore.filter()
                                                    (O(log n) bisect)
                                                          │
                                                    Structured Dict
                                                          │
                                              LLM synthesises response
                                                          │
                                                    User sees answer
```

### Agent Orchestration

The agent uses a **ReAct (Reason + Act)** loop:

1. **Receive** user query + conversation history
2. **LLM decides** which tool(s) to call (or asks a clarifying question)
3. **Execute** tool → returns structured dict (JSON-serializable)
4. **LLM synthesises** a human-readable response from tool output
5. **Multi-turn**: tool results are preserved in conversation history for follow-up questions

Key orchestration features:
- **Sliding-window history** with strict user/assistant pair pruning (no orphaned messages)
- **Tool memory**: intermediate tool calls and their results are appended to conversation history
- **Multi-provider**: hot-swappable between Gemini and OpenAI-compatible APIs
- **System prompt** enforces tool-first behaviour, clarifying questions for ambiguous queries, and multi-step reasoning chains

---

## Tool Functions

### Tool 1: `detect_slow_requests`

```python
detect_slow_requests(
    service: str = None,        # Filter to specific service (or all)
    threshold_ms: float = 2000, # Response time threshold
    time_window: str = "1h"     # Lookback window
)
```

**What it does:**
- Finds requests exceeding the threshold response time
- Groups by endpoint to identify consistently slow paths
- Detects **spike windows** (3+ slow requests within 5 minutes)
- Returns top 10 slowest requests with full latency breakdown (DB / External API / App Logic / Unaccounted)
- Excludes fast failures (4xx < 100ms = load balancer rejects, not real latency)

**Returns:** Endpoint profiles with P50/P90/max, severity labels, spike timestamps, and individual slow request details.

---

### Tool 2: `diagnose_latency_sources`

```python
diagnose_latency_sources(
    service: str = None,          # Filter to specific service
    endpoint: str = None,         # Filter to specific endpoint
    time_window: str = "1h",      # Current analysis window
    baseline_window: str = "24h"  # Historical baseline window
)
```

**What it does:**
- Breaks down latency into **4 components**: Database, External API, App Logic, Network/Queue
- Identifies the **primary bottleneck** (component consuming the most time)
- Compares current performance against a historical baseline (disjoint windows)
- Calculates delta percentage and severity per endpoint group
- Reports **coverage warnings** when < 90% of entries have timing breakdown data

**Returns:** Per-endpoint profiles with current vs baseline medians, severity, and full latency breakdowns with bottleneck attribution.

**Example output interpretation:**
```
Total Response Time: 3,245ms
├─ Database Queries:  1,200ms (37%)
├─ External APIs:     1,800ms (55%) ← PRIMARY BOTTLENECK
├─ Application Logic:   245ms (8%)
└─ Network/Queue:         0ms (0%)
```

---

### Tool 3: `analyze_error_patterns`

```python
analyze_error_patterns(
    service: str = None,        # Filter to specific service
    time_window: str = "1h",    # Lookback window
    group_by: str = "endpoint"  # Group: endpoint|error_type|event_type|provider
)
```

**What it does:**
- Differentiates **client (4xx)** vs **server (5xx)** errors
- Tracks retry counts and affected user counts per error bucket
- Computes **accurate failure rates** (denominator is request-only events, not all logs)
- Detects **WARN-level stress signals** (retries, throttling, degradation patterns)
- WARNs are NOT counted as errors unless they carry a 5xx status code
- Supports `group_by="provider"` for notification delivery analysis (Twilio vs SendGrid)

**Returns:** Error buckets sorted by count, failure rates, affected users, and separate stress signals.

---

### Tool 4: `check_resource_usage`

```python
check_resource_usage(
    service: str = None,   # Filter to specific service
    time_window: str = "1h" # Lookback window
)
```

**What it does:**
- **All services**: Error Rate (ERROR/5xx only), Warn/Throttle Rate (excludes 5xx overlap)
- **payment_api**: DB slow queries (with missing index detection), external API timeouts, connection pool exhaustion, DB catastrophic outliers (> 3s)
- **charging_controller**: Hardware errors, abnormal state transitions (to error/fault), session completion rate, station error grouping, energy anomalies (< 1 kWh), recurring issues
- **notification_service**: Queue wait times (P50/P90), queue depth/backlog with burn rate, retry exhaustion, delivery failures

**Returns:** List of health indicators with severity (NORMAL / MEDIUM / HIGH / CRITICAL) and actionable detail strings.

---

## Performance Thresholds

### Baseline Severity (Latency)

| Severity | Condition | Meaning |
|----------|-----------|---------|
| **CRITICAL** | ≥ 10x baseline median | Major incident — service severely degraded |
| **HIGH** | ≥ 5x baseline median | Significant degradation — investigate immediately |
| **MEDIUM** | ≥ 2x baseline median | Noticeable slowdown — monitor closely |
| **NORMAL** | < 2x baseline | Within expected range |

Baseline is calculated as the **median response time** over the baseline window (default: past 24 hours). The current and baseline windows are **disjoint** (no overlap) to avoid contaminating the comparison.

### Resource Health Severity

| Indicator | CRITICAL | HIGH | MEDIUM |
|-----------|----------|------|--------|
| Error Rate | > 15% | > 10% | > 5% |
| DB Slow Queries | — | > 10 events | > 3 events |
| External API Timeouts | — | > 5 events | > 1 event |
| Connection Pool Exhaustion | > 5 events | > 2 events | — |
| Queue Depth | > 1000 | > 300 | > 100 |
| Energy Anomalies (< 1 kWh) | > 5 sessions | > 1 session | 1 session |
| Abnormal State Transitions | > 10 events | > 3 events | — |

---

## Key Design Decisions

### 1. Vanilla Python + Direct LLM API Calls
No LangChain/LlamaIndex. The ReAct loop is ~150 lines of straightforward Python with explicit tool dispatch. Easier to debug, extend, and reason about during code review.

### 2. Pydantic for Log Parsing
`LogEntry` is a Pydantic `BaseModel` with a `@field_validator` for UTC enforcement. This gives:
- Automatic type coercion and validation on every log line
- Clear schema documentation via type hints
- Property-based helpers (`effective_response_time_ms`, `is_fast_failure`, `group_key`) that encapsulate cross-service field differences

### 3. O(log n) Bisect Filtering
Logs are sorted once at startup. Time-range queries use `bisect_left`/`bisect_right` on a pre-computed timestamp index — no full-scan list comprehensions. Per-service sub-indexes avoid scanning irrelevant entries.

### 4. Structured Dicts (Not Strings)
All tools return `dict` (JSON-serializable), not pre-formatted ASCII strings. This lets the LLM decide how to present data based on the user's question rather than forcing a fixed format.

### 5. Data Context & Staleness Awareness
Every tool return includes a `data_context` field with:
- `reference_time`: The latest log timestamp (used as "now" for relative windows)
- `is_historical`: `True` if logs are > 1 hour old
- `staleness_warning`: Human-readable note when data isn't fresh

The system prompt instructs the LLM to surface this to the user proactively.

### 6. Fast Failure Exclusion
4xx responses under 100ms are classified as "fast failures" (load balancer rejects) and excluded from latency statistics. **5xx errors are never excluded** — a server crash in 50ms is a real issue, not a routing artefact.

---

## Limitations & Trade-offs

### Known Limitations
1. **Static logs only** — no real-time tailing or streaming. The agent analyses snapshots.
2. **No actual CPU/memory metrics** — resource monitoring uses log-level proxies (slow queries, pool exhaustion, queue depth). True CPU/memory would require metrics integration.
3. **Session duration drift unavailable** — `charging_session_completed` events lack `user_id`, making started→completed joins unreliable. Acknowledged in tool output rather than shipping broken code.
4. **Single-process** — no concurrent request handling. Adequate for the interactive CLI use case.
5. **No persistent storage** — all analysis is in-memory per session. Log data is re-parsed on each agent startup.

### What I'd Improve With More Time
1. **Caching layer** — cache baseline calculations across queries (they rarely change within a session)
2. **Streaming/tailing** — use `watchdog` or `tail -f` for real-time log monitoring
3. **Visualization** — embed Plotly/matplotlib charts for latency distributions and error trends
4. **Test suite** — unit tests for each tool's edge cases (empty logs, single entry, all errors)
5. **MCP server** — expose tools via Model Context Protocol for cross-agent integration
6. **Predictive analysis** — linear regression on error rate trends to forecast SLA breaches

---

## Time Investment

| Phase | Hours (approx.) | What Was Done |
|-------|-----------------|---------------|
| **Phase 0: EDA** | ~1h | Explored log structure, identified field patterns across 3 services |
| **Phase 1: Core Engine** | ~3h | Monolithic prototype — log parsing, all 4 tools, basic agent loop |
| **Phase 2: Production Refactor** | ~4h | Modularised into tools/utils, Pydantic models, bisect optimisation, multi-provider support |
| **Polish & Bug Fixes** | ~3h | 3 rounds of critical patches (UTC handling, WARN overcounting, provider denominator, dead code removal, coverage warnings, request-only denominators) |
| **Documentation** | ~1h | README, system prompt refinement |
| **Total** | **~12h** | |

---

## AI Assistance Used

### How AI Was Used
- **Architecture planning**: AI helped design the tool function signatures and identify edge cases in log data
- **Code generation**: Initial tool implementations were AI-generated, then manually reviewed and iterated on
- **Bug detection**: AI-assisted code review identified 8+ logic bugs (WARN overcounting, broken joins, fast-failure classification, denominator inflation)
- **Refactoring**: AI helped modularise the monolithic Phase 1 into the Phase 2 structure

### What Worked Well
- **Iterative code review** — treating AI as a pair programmer for bug hunting was extremely effective
- **Pattern identification** — AI quickly spotted cross-service field inconsistencies (e.g., `response_time_ms` at root vs in metadata)

### What Didn't Work Well
- **First-pass accuracy** — AI-generated code often had subtle logic bugs that required manual verification (e.g., incorrect join keys, wrong filter conditions)
- **Over-engineering tendency** — had to actively resist AI suggestions to add unnecessary abstractions

---

## Project Structure

```
Phase2/
├── README.md                       # This file
├── requirements.txt                # Python dependencies (5 packages)
├── .env.example                    # Environment variable template
├── .gitignore                      # Excludes .env, __pycache__, .venv
├── agent.py                        # Main orchestrator (ReAct loop, LLM providers)
├── tools/
│   ├── __init__.py                 # Package docstring
│   ├── latency_analysis.py         # detect_slow_requests, diagnose_latency_sources
│   ├── error_analysis.py           # analyze_error_patterns
│   └── resource_monitoring.py      # check_resource_usage
├── prompts/
│   └── system_prompt.txt           # KazamSRE agent persona + rules
├── utils/
│   ├── log_parser.py               # LogEntry (Pydantic) + LogStore (bisect-optimised)
│   └── baseline_calculator.py      # Severity labels, percentile, median, window parser
└── logs/
    ├── payment_api.log             # ~1200 entries
    ├── charging_controller.log     # ~1000 entries
    └── notification_service.log    # ~800 entries
```

---

## Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `pydantic` | ≥ 2.0 | Log entry validation and type coercion |
| `google-genai` | ≥ 1.0 | Gemini LLM provider |
| `openai` | ≥ 1.0 | OpenAI-compatible LLM provider |
| `python-dotenv` | ≥ 1.0 | Environment variable loading |
| `colorama` | ≥ 0.4 | Terminal colour output (Windows) |

All are standard, well-maintained packages. No APM/monitoring platform SDKs are used.
