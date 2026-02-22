# Performance Log Analysis Agent - Take-Home Project

---

## Project Overview

You're building an internal performance monitoring tool for  DevOps team. Our microservices generate application logs with performance metrics, error rates, and resource usage that need real-time analysis during incidents and capacity planning.

**Your mission:** Build an AI agent that lets SRE/DevOps engineers query logs using natural language to diagnose performance issues, identify bottlenecks, and prevent outages.

---

## What We're Providing

### Sample Log Files (in `logs/` directory)

**1. `payment_api.log`** (~1200 lines)
- API request/response times
- Payment processing events
- Database query performance
- Third-party integration latencies

**2. `charging_controller.log`** (~1000 lines)
- Charging session management
- Hardware communication delays
- Timeout events
- State machine transitions

**3. `notification_service.log`** (~800 lines)
- Message queue processing
- Email/SMS delivery times
- Retry attempts
- Rate limiting events

### Log Format (JSON Lines)

```json
{
  "timestamp": "2025-02-19T14:23:45.123Z",
  "service": "payment_api",
  "level": "INFO",
  "event_type": "api_request_completed",
  "endpoint": "/api/v1/payments/process",
  "method": "POST",
  "status_code": 200,
  "response_time_ms": 245,
  "metadata": {
    "user_id": "user_12345",
    "payment_gateway": "stripe",
    "db_query_time_ms": 45,
    "external_api_time_ms": 180,
    "retry_count": 0
  }
}
```

**Event Types You'll Encounter:**
- `api_request_completed`, `api_request_failed`
- `database_query_slow`, `database_timeout`
- `cache_hit`, `cache_miss`
- `external_api_timeout`, `external_api_slow`
- `queue_processing_delayed`, `message_retry`
- `charging_session_timeout`, `hardware_communication_error`
- `memory_usage_high`, `cpu_spike_detected`

---

## Core Requirements (Must Complete)

### 1. Tool Functions (Minimum 4 Required)

You must implement at least these tool functions that your agent can call:

#### **`detect_slow_requests(service: str = None, threshold_ms: int = 2000, time_window: str = "1h")`**
**Purpose:** Identify performance bottlenecks in API endpoints
- Find requests exceeding threshold response time
- Group by endpoint to identify consistent slow paths
- Distinguish between DB slowness, external API delays, and application logic
- Returns: List of slow requests with breakdown of time spent

**Example query:** "Show me API endpoints slower than 2 seconds in the last hour"

#### **`analyze_error_patterns(service: str = None, time_window: str = "6h", group_by: str = "endpoint")`**
**Purpose:** Track error rates and failure patterns
- Count errors by type (4xx vs 5xx)
- Identify error spikes (sudden increase in failures)
- Correlate errors with specific endpoints, users, or time periods
- Returns: Error distribution with trend analysis

**Example query:** "What's causing the spike in 5xx errors?"

#### **`check_resource_usage(service: str, time_window: str = "24h")`**
**Purpose:** Monitor system resource consumption
- Track memory usage patterns
- Identify CPU spikes
- Detect resource exhaustion events
- Correlate resource usage with request load
- Returns: Resource usage trends with anomaly indicators

**Example query:** "Is the payment service having memory issues?"

#### **`diagnose_latency_sources(endpoint: str, time_window: str = "1h")`**
**Purpose:** Break down where time is spent in slow requests
- Separate: database time, external API calls, application processing, network latency
- Identify primary bottleneck (what's taking the most time)
- Compare against baseline performance
- Returns: Latency breakdown with recommendations

**Example query:** "Why is /api/v1/payments/process so slow right now?"

### 2. Natural Language Interface

Your agent must respond intelligently to performance queries like:

**Performance Investigation:**
- "What's the slowest endpoint right now?"
- "Show me all requests that took longer than 5 seconds"
- "Why is the payment API slow today?"

**Error Analysis:**
- "What's the error rate for the charging controller in the last hour?"
- "Are we seeing more 500 errors than usual?"
- "Which endpoint is failing most frequently?"

**Trend Analysis:**
- "Compare response times: this hour vs. last hour"
- "Is performance getting worse over time?"
- "Show me the top 3 bottlenecks"

**Resource Monitoring:**
- "Is any service running out of memory?"
- "Check CPU usage for the notification service"
- "Are we seeing any resource exhaustion?"

**Root Cause Analysis (Multi-Step):**
- "Find slow requests, then check if they're hitting database timeouts"
- "Show me errors, then analyze their distribution by time of day"

### 3. Performance-Specific Requirements

#### **Baseline Comparison**
Implement simple baseline detection:
```
CRITICAL: >10x worse than baseline (median response time)
HIGH: 5-10x worse than baseline
MEDIUM: 2-5x worse than baseline  
NORMAL: Within expected range
```

#### **Latency Breakdown**
When analyzing slow requests, provide time attribution:
```
Total Response Time: 3,245ms
├─ Database Queries: 1,200ms (37%) ← PRIMARY BOTTLENECK
├─ External APIs: 1,800ms (55%) ← SECONDARY BOTTLENECK
├─ Application Logic: 245ms (8%)
└─ Network/Other: 0ms (0%)

Recommendation: Investigate external API timeouts (Stripe gateway)
```

#### **Impact Assessment**
When reporting issues, include:
- Affected user count (how many requests)
- Failure rate percentage
- Duration of the issue (first seen → last seen)
- Severity based on SLA impact

---

## Agent Behavior Guidelines

### System Prompt Structure

Your agent should:
1. **Always call tool functions** before answering performance questions
2. **Provide context** - not just raw numbers, but what they mean
3. **Suggest next steps** - investigation paths or fixes
4. **Ask clarifying questions** when queries are ambiguous
   - "Which service should I check?"
   - "What's your acceptable response time threshold?"

### Example Interaction Flow

```
User: "The system feels slow"

Agent (Internal Reasoning):
1. Vague query - need to scope it
2. "Slow" is subjective - need to check multiple services
3. Should start with most critical user-facing services

Agent Response:
"I'll investigate performance across our services. Let me start with user-facing APIs.

[Calling detect_slow_requests() for payment_api, charging_controller...]

Performance Analysis - Last Hour:

CRITICAL Issue Found:
Payment API (/api/v1/payments/process):
- Average response time: 4,234ms (baseline: 350ms) → 12x slower 
- Affected: 156 requests (45% of traffic)
- Primary bottleneck: External API timeouts (Stripe)
  - Stripe API: 3,200ms avg (normally 150ms)
  
Recommendation:
1. Check Stripe status page for outages
2. Review timeout configuration (currently 30s)
3. Consider fallback payment processor

MEDIUM Issue:
Charging Controller:
- 5 hardware communication timeouts detected
- Locations: Station_042, Station_103
- Impact: 5 charging sessions failed to start

Notification Service: NORMAL
- Avg processing time: 85ms (within baseline)

Would you like me to:
1. Deep dive into the Stripe integration latency?
2. Check error logs for affected payment requests?
3. Analyze if this correlates with increased traffic?"
```

---

## Deliverables Checklist

### 1. Code Repository Structure

```
performance-agent/
├── README.md                   # Setup + usage instructions
├── requirements.txt            # Python dependencies
├── .env.example               # Environment variables template
├── agent.py                   # Main agent orchestration
├── tools/
│   ├── __init__.py
│   ├── latency_analysis.py    # Response time tools
│   ├── error_analysis.py      # Error tracking tools
│   └── resource_monitoring.py # CPU/memory tools
├── prompts/
│   └── system_prompt.txt      # Agent instructions
├── utils/
│   ├── baseline_calculator.py # Baseline comparisons
│   └── log_parser.py          # Log parsing utilities
├── logs/                      # Sample logs (provided)
│   ├── payment_api.log
│   ├── charging_controller.log
│   └── notification_service.log
├── tests/                     # Optional but impressive
│   └── test_tools.py
└── demo/
    └── example_queries.txt    # Sample queries to test
```

### 2. README.md Requirements

Must include:

```markdown
# Performance Log Analysis Agent

## Quick Start
[Step-by-step setup - should work in <5 minutes]

## Usage
[How to run the agent]
[Example queries with expected outputs]

## Architecture
[High-level diagram or explanation]
[Tool function responsibilities]

## Performance Thresholds
[How you define "slow", "error spike", etc.]
[Baseline calculation methodology]

## Limitations & Trade-offs
[What doesn't work yet]
[What you'd improve with more time]
[Design decisions and their rationale]

## Time Investment
[Honest breakdown: ~X hours on different components]

## AI Assistance Used
[How you leveraged AI coding tools]
[What worked well, what didn't]
```

### 3. Demo (Choose One)

**Option A: Video Demo** (Preferred)
- 2-3 minute screen recording
- Show 3-5 different performance queries
- Include both normal and degraded performance scenarios
- Upload to Google Drive/YouTube (unlisted) and share link

**Option B: Live Demo** (During Code Review)
- Be prepared to run 5 queries live
- Show how agent handles edge cases
- Have backup recordings just in case

---

## ⚡ Bonus Challenges (Optional - Extra Credit)

Choose any to demonstrate advanced skills:
### Bonus 1: Intelligent Caching & Cost Optimization (+30 points)
- Cache baseline calculations (don't recompute for every query)
- Implement smart sampling (analyze subset of logs when appropriate)
- Minimize LLM token usage with structured outputs
- Document cost per query with before/after optimization

### Bonus 2: MCP Server Implementation (+20 points)
- Expose your performance tools as an MCP (Model Context Protocol) server
- Document server setup and client connection
- Show how other agents can call your performance tools
- Include examples of cross-agent communication

**Resources:**
- MCP documentation: https://modelcontextprotocol.io
- Example servers: https://github.com/modelcontextprotocol/servers

### Bonus 3: Real-Time Streaming Analysis (+15 points)
- Implement log tailing for real-time monitoring
- Show how agent handles continuously updating logs
- Demonstrate live alerting for performance degradation
- Use `tail -f` simulation or file watching

### Bonus 4: Performance Visualization (+15 points)
- Generate time-series charts for response times
- Create latency distribution histograms
- Show error rate trends over time
- Use matplotlib/plotly, embed in agent responses or save to files


### Bonus 5: Predictive Analysis (+10 points)
- Detect degradation trends before they become critical
- Forecast: "If error rate continues, we'll exceed SLA in 2 hours"
- Use simple linear regression or moving averages
- Provide proactive recommendations

---

## Evaluation Criteria (100 Points Total)

| Category | Points | What We're Looking For |
|----------|--------|----------------------|
| **Tool Design** | 25 | Clean function interfaces, proper parameter validation, meaningful return values |
| **Agent Orchestration** | 25 | Correct tool selection, context awareness, multi-step reasoning |
| **Performance Logic** | 20 | Accurate bottleneck detection, proper baseline comparison, actionable insights |
| **Code Quality** | 15 | Readable, well-structured, follows best practices, proper error handling |
| **User Experience** | 10 | Clear explanations, helpful responses, graceful error handling |
| **Documentation** | 5 | README that works, clear examples, honest limitations |
| **Bonus Features** | +60 max | Optional challenges completed well |

---

## Rules & Constraints

### You CAN:
- Use any LLM API (OpenAI GPT-4, Anthropic Claude, Google Gemini, or local models)
- Use AI coding assistants (GitHub Copilot, Cursor, Claude Code, ChatGPT)
- Use any Python libraries or frameworks (LangChain, LlamaIndex, plain Python, etc.)
- Use any storage solution (SQLite, JSON files, in-memory dictionaries)
- Implement simple statistics (percentiles, averages, trends)
- Simplify scope if time-constrained (document what and why)
- Ask clarifying questions via email

### You CANNOT:
- Spend more than **16 hours total** (self-reported, honor system)
- Use existing APM/monitoring platforms (DataDog SDK, New Relic, Prometheus client libraries)
- Submit code that doesn't run without explaining why
- Skip documentation (we won't debug setup issues)
- Use complex ML models (simple statistics are preferred for 2-day scope)

### Important Notes:
- **Working code beats perfect code** - ship something functional
- **Explain trade-offs** - why you chose this approach over alternatives
- **Be honest about AI usage** - we want to see effective AI collaboration, not hide it
- **Document limitations** - shows engineering maturity

---

## Timeline

- **Day 0 (Today):** Project sent, start when ready
- **Day 2 (48 hours from now):** Submission deadline - 11:59 PM
- **Day 3:** Code review session scheduled (30-min slot)

---

## Submission Instructions

**Send to:** faizal@kazam.in, diya@kazam.in

**Subject:** "Performance Agent Submission - [Your Name]"

**Include:**
1. **Code delivery:**
   - GitHub repository link (preferred) OR
   - Zip file with complete project
   
2. **Demo:**
   - Video link (Google Drive/YouTube unlisted) OR
   - Confirmation you'll demo live during review
   
3. **Project summary** (3-5 sentences):
   - Your architectural approach
   - Biggest technical challenge solved
   - Time breakdown (rough hours: planning, coding, testing, docs)
   - One thing you'd improve with more time

4. **Self-assessment:**
   - What went well?
   - What was harder than expected?
   - How did AI tools help/hinder?

---

## Tips for Success

### Getting Started Fast (First 2 Hours)
1. **Parse logs successfully** - get basic JSON parsing working
2. **Implement ONE simple tool** - `detect_slow_requests()` with hardcoded threshold
3. **Get agent calling it** - even with a basic prompt
4. **Verify end-to-end flow** - query → tool call → response
5. **Then iterate** - add complexity gradually

### Time Management Strategy
```
Hour 0-2:   Basic parsing + one tool + simple agent
Hour 2-4:   Second and third tools, improve parsing
Hour 4-6:   Fourth tool, better agent orchestration
Hour 6-8:   Prompt engineering, multi-turn conversations
Hour 8-10:  Error handling, edge cases, baseline logic
Hour 10-12: Documentation, demo preparation
Hour 12-14: Polish, testing, bonus features if time
Hour 14-16: Buffer for debugging, final testing
```

### Common Pitfalls to Avoid
- **Over-engineering log parsing** (basic JSON parsing is fine, don't build a whole log pipeline)
- **Complex statistics** (averages and percentiles are enough, skip ML models)
- **Perfect baselines** (simple median calculation is fine for 2-day project)
- **Too many tools** (4 solid tools beat 8 buggy ones)
- **No testing** (at least manually test your example queries)

### What Impresses Us
- **Runs immediately** - clear setup, no debugging needed
- **Thoughtful error handling** - "No slow requests found in this period" vs crashing
- **Actionable insights** - not just numbers, but what they mean and what to do
- **Honest documentation** - "Doesn't support compressed logs yet because..."
- **Iterative thinking** - evidence of trying different approaches
- **Smart AI usage** - show how you used and validated AI-generated code

---

## Frequently Asked Questions

**Q: What LLM should I use?**
A: Use any LLM you prefer. Optimize with caching, smaller models for simple tasks.

**Q: Should I implement real statistical analysis or keep it simple?**
A: Keep it simple! Medians, percentiles, and basic trend detection (this hour vs last hour) are sufficient. Don't build complex time-series models.

**Q: What if I can't finish all 4 tool functions?**
A: Submit what you have! We'd rather see 3 excellent, well-documented tools than 4 half-working ones. Explain what you'd add next.

**Q: Can I use AI to write code for me?**
A: Absolutely! We want to see how effectively you collaborate with AI tools. Just ensure you understand the code you submit (you'll explain it during review).

**Q: The provided logs are static. Should I simulate streaming?**
A: Not required for core project. If you want to tackle "Bonus 2: Real-Time Streaming", go for it, but not necessary.

**Q: How accurate should baseline calculations be?**
A: Simple median calculation over the time window is fine. You can use a moving average for trend detection. Don't overthink it.

**Q: What if my agent occasionally gives wrong answers?**
A: That's realistic! Document known issues and show your validation strategy. Bonus points for discussing how you'd improve accuracy.

**Q: Should I use a framework like LangChain?**
A: Your choice. We care about your thinking, not the framework. Vanilla Python with direct LLM API calls is totally acceptable.

**Q: Can I reach out if I'm blocked?**
A: Yes! Email faizal@kazam.in with:
- What you tried
- What's not working
- Your hypothesis on the issue
  
We'll respond within 4 hours during business hours.

---

## Learning Resources (Optional)

If you need a refresher on any concepts:

**Agent Design:**
- LangChain Agents: https://python.langchain.com/docs/modules/agents/
- OpenAI Function Calling: https://platform.openai.com/docs/guides/function-calling
- Anthropic Tool Use: https://docs.anthropic.com/en/docs/build-with-claude/tool-use

**Prompt Engineering:**
- Anthropic Prompt Library: https://docs.anthropic.com/en/prompt-library/
- OpenAI Prompt Engineering Guide: https://platform.openai.com/docs/guides/prompt-engineering

**Performance Engineering Concepts:**
- Site Reliability Engineering (SRE) Basics: https://sre.google/sre-book/table-of-contents/
- Application Performance Monitoring: https://www.datadoghq.com/knowledge-center/apm/

**Python Best Practices:**
- Real Python: https://realpython.com/
- Python Type Hints: https://docs.python.org/3/library/typing.html

---

## What Success Looks Like

### Minimum Viable Submission
```
 4 tool functions implemented and working
 Agent calls correct tools for queries
 README with setup instructions that work
 Code runs without errors on basic queries
 Demo showing 3-5 different query types
 Honest documentation of limitations
```

### Impressive Submission
```
 All of the above, plus:
 Handles edge cases gracefully (empty logs, malformed data)
 Provides actionable insights, not just data dumps
 Multi-step reasoning (correlates issues across logs)
 Clear code structure with good separation of concerns
 Evidence of iteration and testing
 At least one bonus challenge completed
 Thoughtful discussion of trade-offs in README
```

---

## What We're Really Evaluating

Beyond the code itself, we're assessing:

### 1. **Problem Decomposition**
- Can you break down "diagnose performance issues" into concrete tool functions?
- Do you identify the right abstraction boundaries?

### 2. **Engineering Judgment**
- When do you use simple solutions vs. complex ones?
- How do you balance completeness vs. time constraints?
- What trade-offs do you make, and can you articulate why?

### 3. **Production Thinking**
- How do you handle errors and edge cases?
- Do you think about costs, scalability, and maintainability?
- Are your responses actionable for a real engineer?

### 4. **AI Collaboration**
- How effectively do you use AI coding assistants?
- Do you blindly accept AI suggestions or critically evaluate them?
- Can you debug AI-generated code?

### 5. **Communication**
- Can you explain complex technical concepts clearly?
- Is your documentation helpful for someone unfamiliar with your code?
- Do you articulate limitations and next steps?

### 6. **Learning Agility**
- How do you approach unfamiliar problems?
- Do you iterate and improve based on testing?
- Can you pivot when something doesn't work?

---

## Real-World Context

This project mirrors actual work you'd do as an AI Application Development Intern:

**Week 1-2:** You'd build similar tools for internal observability
**Week 3-4:** Extend to handle our actual production logs
**Week 5-6:** Integrate with our alerting systems (PagerDuty, Slack)
**Week 7-8:** Add cost optimization and advanced analytics

So this isn't just a test - it's representative of your actual work. We're looking for someone who can:
- Ship working tools quickly
- Think like an SRE/DevOps engineer
- Iterate based on feedback
- Balance speed with quality

---

## Final Encouragement

**Remember:**
- Simple and working beats complex and broken
- Document your thinking, not just your code
- Ask questions if requirements are unclear
- Use AI tools effectively (that's a feature, not cheating)
- Have fun! Performance analysis is detective work 

We're not looking for perfect code - we're looking for thoughtful engineers who can ship practical solutions to real problems.

**You got this!** 

---

**Questions or need clarification?**  
Email: faizal@kazam.in, diya@kazam.in

**Want to discuss your approach before diving in?**  
Feel free to send a quick architecture sketch for feedback (optional, not required).

---

Good luck! We're excited to see your agent in action.
