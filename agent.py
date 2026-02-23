"""
agent.py -- Multi-Model SRE Agent Orchestrator
===============================================
ReAct loop with function calling, supporting:
  - Google Gemini  (native SDK)
  - OpenAI-compatible APIs  (DeepSeek, ZLM, local models)

REFACTORED:
  - MAX_TOOL_CALLS_PER_TURN = 10
  - execute_tool: JSON error dicts (no traceback), dict→JSON serialization
  - chat(): sliding window history truncation (last 10 messages)
  - Smoke test updated for dict assertions

Usage:
    python agent.py              # Interactive CLI
    python agent.py --smoke      # Run smoke test on tools

Environment variables (.env):
    LLM_PROVIDER     = "gemini" | "openai"
    GEMINI_API_KEY    = ...
    GEMINI_MODEL      = gemini-2.0-flash
    OPENAI_API_KEY    = ...
    OPENAI_BASE_URL   = https://api.deepseek.com/v1
    OPENAI_MODEL      = deepseek-chat
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from dotenv import load_dotenv

# ── Colorama for Windows terminal colors ─────────────────
try:
    from colorama import Fore, Style, init as colorama_init
    colorama_init(autoreset=True)
except ImportError:
    # Fallback: no colors
    class _Stub:
        def __getattr__(self, _: str) -> str:
            return ""
    Fore = Style = _Stub()

# ── Load local modules ───────────────────────────────────
from utils.log_parser import LogStore
from tools.latency_analysis import detect_slow_requests, diagnose_latency_sources
from tools.error_analysis import analyze_error_patterns
from tools.resource_monitoring import check_resource_usage
from tools.visualization import generate_latency_chart, generate_error_heatmap


# ==============================================================
#  Tool Registry
# ==============================================================

# Resolve paths
BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"
PROMPT_FILE = BASE_DIR / "prompts" / "system_prompt.txt"

# Global LogStore (loaded once at startup)
_store: Optional[LogStore] = None


def get_store() -> LogStore:
    """Lazy-init the LogStore singleton."""
    global _store
    if _store is None:
        print(f"{Fore.CYAN}[System] Loading logs from {LOG_DIR}...{Style.RESET_ALL}")
        _store = LogStore(LOG_DIR)
        print(
            f"{Fore.CYAN}[System] Loaded {len(_store.entries)} entries, "
            f"parse errors: {len(_store.parse_errors)}, "
            f"reference_time: {_store.reference_time.isoformat()}{Style.RESET_ALL}"
        )
        print(f"{Fore.CYAN}[System] Charts directory: {BASE_DIR / 'charts'}{Style.RESET_ALL}")
    return _store


# ── Tool wrapper functions (bridge between LLM args and tool modules) ──

def tool_detect_slow_requests(
    service: Optional[str] = None,
    threshold_ms: float = 2000.0,
    time_window: str = "1h",
) -> dict:
    return detect_slow_requests(get_store(), service=service, threshold_ms=threshold_ms, time_window=time_window)


def tool_diagnose_latency_sources(
    service: Optional[str] = None,
    endpoint: Optional[str] = None,
    time_window: str = "1h",
    baseline_window: str = "24h",
) -> dict:
    return diagnose_latency_sources(get_store(), service=service, endpoint=endpoint, time_window=time_window, baseline_window=baseline_window)


def tool_analyze_error_patterns(
    service: Optional[str] = None,
    time_window: str = "1h",
    group_by: str = "endpoint",
) -> dict:
    return analyze_error_patterns(get_store(), service=service, time_window=time_window, group_by=group_by)


def tool_check_resource_usage(
    service: Optional[str] = None,
    time_window: str = "1h",
) -> dict:
    return check_resource_usage(get_store(), service=service, time_window=time_window)


def tool_generate_latency_chart(
    service: Optional[str] = None,
    time_window: str = "24h",
) -> dict:
    return generate_latency_chart(get_store(), service=service, time_window=time_window)


def tool_generate_error_heatmap(
    time_window: str = "48h",
) -> dict:
    return generate_error_heatmap(get_store(), time_window=time_window)


# ── Registry: name -> (function, JSON schema) ──

TOOL_FUNCTIONS: Dict[str, Callable] = {
    "detect_slow_requests": tool_detect_slow_requests,
    "diagnose_latency_sources": tool_diagnose_latency_sources,
    "analyze_error_patterns": tool_analyze_error_patterns,
    "check_resource_usage": tool_check_resource_usage,
    "generate_latency_chart": tool_generate_latency_chart,
    "generate_error_heatmap": tool_generate_error_heatmap,
}

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "detect_slow_requests",
            "description": "Find requests exceeding a latency threshold and identify incident spike windows. Returns a JSON object with endpoint profiles, P50/P90 stats, spike windows, and Top 10 slowest requests.",
            "parameters": {
                "type": "object",
                "properties": {
                    "service": {
                        "type": "string",
                        "enum": ["payment_api", "charging_controller", "notification_service"],
                        "description": "Filter by service. Omit or set to null for all services.",
                    },
                    "threshold_ms": {
                        "type": "number",
                        "default": 2000.0,
                        "description": "Latency threshold in ms. Requests slower than this are flagged. Use 500 for payment_api, 2000 for general.",
                    },
                    "time_window": {
                        "type": "string",
                        "default": "1h",
                        "description": "How far back to look. Examples: '1h', '6h', '24h', '48h'.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "diagnose_latency_sources",
            "description": "Break down latency into DB, External API, App Logic, and Network/Queue components. Compares current window against a disjoint historical baseline to detect regressions. Returns JSON with profiles and component breakdowns.",
            "parameters": {
                "type": "object",
                "properties": {
                    "service": {
                        "type": "string",
                        "enum": ["payment_api", "charging_controller", "notification_service"],
                        "description": "Filter by service. Omit for all services.",
                    },
                    "endpoint": {
                        "type": "string",
                        "description": "Filter by specific endpoint (e.g., '/payments/process'). Omit for all endpoints.",
                    },
                    "time_window": {
                        "type": "string",
                        "default": "1h",
                        "description": "Current analysis window. Examples: '1h', '6h', '24h'.",
                    },
                    "baseline_window": {
                        "type": "string",
                        "default": "24h",
                        "description": "Historical baseline window for comparison. Must be larger than time_window.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_error_patterns",
            "description": "Analyze error distribution: differentiates 4xx vs 5xx, computes per-group failure rates, tracks retry patterns, and detects WARN-level pre-error stress signals. Returns JSON with error buckets and stress signals.",
            "parameters": {
                "type": "object",
                "properties": {
                    "service": {
                        "type": "string",
                        "enum": ["payment_api", "charging_controller", "notification_service"],
                        "description": "Filter by service. Omit for all services.",
                    },
                    "time_window": {
                        "type": "string",
                        "default": "1h",
                        "description": "How far back to look. Examples: '1h', '6h', '24h'.",
                    },
                    "group_by": {
                        "type": "string",
                        "enum": ["endpoint", "error_type", "event_type", "provider"],
                        "default": "endpoint",
                        "description": "How to group errors. 'endpoint' for per-route, 'error_type' for error messages, 'event_type' for event categories.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_resource_usage",
            "description": "Monitor service health: error rates (strict ERROR/5xx), warn/throttle rates, DB connection pool exhaustion, queue depth with backlog burn rate, hardware errors, session completion rate, retry exhaustion, delivery failures, and missing DB index detection. Returns JSON with per-service health indicators.",
            "parameters": {
                "type": "object",
                "properties": {
                    "service": {
                        "type": "string",
                        "enum": ["payment_api", "charging_controller", "notification_service"],
                        "description": "Filter by service. Omit for all services.",
                    },
                    "time_window": {
                        "type": "string",
                        "default": "1h",
                        "description": "How far back to look. Examples: '1h', '6h', '24h'.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_latency_chart",
            "description": "Generate a scatter plot of response_time_ms over time with a rolling median trend line and spike window overlays. Call when the user says 'show', 'plot', 'chart', 'graph', 'visualize', 'trend', 'over time', or 'timeline'. Returns the filepath of the saved PNG.",
            "parameters": {
                "type": "object",
                "properties": {
                    "service": {
                        "type": "string",
                        "enum": ["payment_api", "charging_controller", "notification_service"],
                        "description": "Filter by service. Omit or null for all services (color-coded by service).",
                    },
                    "time_window": {
                        "type": "string",
                        "default": "24h",
                        "description": "How far back to look. Examples: '6h', '24h', '48h'.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_error_heatmap",
            "description": "Generate a heatmap of error counts per hour × service. Call when the user says 'heatmap', 'error distribution', 'when did errors', 'error pattern over time', or 'which hour'. Returns the filepath of the saved PNG.",
            "parameters": {
                "type": "object",
                "properties": {
                    "time_window": {
                        "type": "string",
                        "default": "48h",
                        "description": "Width of the heatmap window. Examples: '24h', '48h'. Each row = 1 hour.",
                    },
                },
                "required": [],
            },
        },
    },
]


# ==============================================================
#  Tool Execution (JSON-safe, no tracebacks to LLM)
# ==============================================================

MAX_TOOL_CALLS_PER_TURN = 10
MAX_HISTORY_MESSAGES = 10


def execute_tool(name: str, arguments: Dict[str, Any]) -> str:
    """Execute a tool by name.  Always returns a JSON string."""
    func = TOOL_FUNCTIONS.get(name)
    if not func:
        return json.dumps({
            "error": f"Unknown tool '{name}'",
            "available_tools": list(TOOL_FUNCTIONS.keys()),
        })
    try:
        # Filter out None values so defaults are used
        clean_args = {k: v for k, v in arguments.items() if v is not None}
        result = func(**clean_args)
        # Dict -> JSON string for LLM context
        if isinstance(result, dict):
            return json.dumps(result, default=str)
        return str(result)
    except Exception as exc:
        return json.dumps({
            "error": "Tool execution failed",
            "tool": name,
            "details": str(exc),
        })


# ==============================================================
#  LLM Providers
# ==============================================================

class GeminiProvider:
    """Google Gemini via google-genai SDK."""

    def __init__(self):
        from google import genai
        from google.genai import types

        api_key = os.getenv("GEMINI_API_KEY", "")
        if not api_key:
            raise ValueError("GEMINI_API_KEY not set in .env")

        self.client = genai.Client(api_key=api_key)
        self.model = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
        self.types = types

    def _build_tools(self):
        """Convert our tool schemas to Gemini's tool format."""
        declarations = []
        for schema in TOOL_SCHEMAS:
            fn = schema["function"]

            # Clean up properties - remove unsupported keys for Gemini
            clean_props = {}
            for prop_name, prop_def in fn["parameters"]["properties"].items():
                clean_prop = {"type": prop_def["type"]}
                if "description" in prop_def:
                    clean_prop["description"] = prop_def["description"]
                if "enum" in prop_def:
                    clean_prop["enum"] = prop_def["enum"]
                clean_props[prop_name] = clean_prop

            declarations.append(self.types.FunctionDeclaration(
                name=fn["name"],
                description=fn["description"],
                parameters={
                    "type": "object",
                    "properties": clean_props,
                    "required": fn["parameters"].get("required", []),
                },
            ))

        return self.types.Tool(function_declarations=declarations)

    def chat(self, messages: List[Dict], system_prompt: str) -> str:
        """Run the ReAct loop with Gemini.  Returns (text, tool_log)."""
        tool = self._build_tools()

        # Build Gemini content list from messages
        contents = []
        for msg in messages:
            if msg["role"] == "user":
                contents.append(self.types.Content(
                    role="user",
                    parts=[self.types.Part.from_text(text=msg["content"])],
                ))
            elif msg["role"] == "assistant":
                contents.append(self.types.Content(
                    role="model",
                    parts=[self.types.Part.from_text(text=msg["content"])],
                ))

        tool_call_count = 0
        tool_log: List[Dict[str, Any]] = []  # Track tool exchanges for history

        while tool_call_count < MAX_TOOL_CALLS_PER_TURN:
            response = self.client.models.generate_content(
                model=self.model,
                contents=contents,
                config=self.types.GenerateContentConfig(
                    tools=[tool],
                    system_instruction=system_prompt,
                    temperature=0.2,
                ),
            )

            # Check for function calls
            candidate = response.candidates[0]
            parts = candidate.content.parts

            has_function_call = any(
                p.function_call is not None and p.function_call.name
                for p in parts
            )

            if not has_function_call:
                # Final text response
                text_parts = [p.text for p in parts if p.text]
                final_text = "\n".join(text_parts) if text_parts else "I could not generate a response."
                return final_text, tool_log

            # Process function calls
            contents.append(candidate.content)

            function_response_parts = []
            for part in parts:
                if part.function_call is not None and part.function_call.name:
                    fc = part.function_call
                    tool_call_count += 1

                    args = dict(fc.args) if fc.args else {}
                    print(
                        f"{Fore.YELLOW}  [Executing Tool: {fc.name}("
                        f"{', '.join(f'{k}={v!r}' for k, v in args.items())})]{Style.RESET_ALL}"
                    )

                    result = execute_tool(fc.name, args)

                    print(f"{Fore.BLUE}  [Tool Result: {len(result)} chars]{Style.RESET_ALL}")

                    tool_log.append({"tool": fc.name, "args": args, "result_length": len(result)})

                    function_response_parts.append(
                        self.types.Part.from_function_response(
                            name=fc.name,
                            response={"result": result},
                        )
                    )

            contents.append(self.types.Content(
                role="user",
                parts=function_response_parts,
            ))

        return "I've reached the maximum number of tool calls for this turn. Please refine your question.", tool_log


class OpenAIProvider:
    """OpenAI-compatible provider (DeepSeek, ZLM, local models)."""

    def __init__(self):
        from openai import OpenAI

        api_key = os.getenv("OPENAI_API_KEY", "")
        base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        if not api_key:
            raise ValueError("OPENAI_API_KEY not set in .env")

        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = os.getenv("OPENAI_MODEL", "gpt-4")

    def chat(self, messages: List[Dict], system_prompt: str):
        """Run the ReAct loop with OpenAI-compatible API.  Returns (text, tool_log)."""
        full_messages = [{"role": "system", "content": system_prompt}] + messages

        tool_call_count = 0
        tool_log: List[Dict[str, Any]] = []

        while tool_call_count < MAX_TOOL_CALLS_PER_TURN:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=full_messages,
                tools=TOOL_SCHEMAS,
                tool_choice="auto",
                temperature=0.2,
            )

            choice = response.choices[0]

            if choice.finish_reason == "stop" or not choice.message.tool_calls:
                return (choice.message.content or "I could not generate a response."), tool_log

            # Process tool calls
            assistant_msg = choice.message
            full_messages.append({
                "role": "assistant",
                "content": assistant_msg.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in assistant_msg.tool_calls
                ],
            })

            for tc in assistant_msg.tool_calls:
                tool_call_count += 1
                func_name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {}

                print(
                    f"{Fore.YELLOW}  [Executing Tool: {func_name}("
                    f"{', '.join(f'{k}={v!r}' for k, v in args.items())})]{Style.RESET_ALL}"
                )

                result = execute_tool(func_name, args)
                print(f"{Fore.BLUE}  [Tool Result: {len(result)} chars]{Style.RESET_ALL}")

                tool_log.append({"tool": func_name, "args": args, "result_length": len(result)})

                full_messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })

        return "I've reached the maximum number of tool calls for this turn. Please refine your question.", tool_log


# ==============================================================
#  Agent Class
# ==============================================================

class SREAgent:
    """Multi-model SRE agent with ReAct loop and history management."""

    def __init__(self):
        load_dotenv(BASE_DIR / ".env")

        self.provider_name = os.getenv("LLM_PROVIDER", "gemini").lower()
        self.system_prompt = self._load_system_prompt()
        self.conversation_history: List[Dict[str, str]] = []
        self.provider = self._init_provider()

        # Pre-load the LogStore so it's warmed up
        get_store()

    def _load_system_prompt(self) -> str:
        """Load the system prompt from file."""
        if PROMPT_FILE.exists():
            return PROMPT_FILE.read_text(encoding="utf-8")
        return "You are a helpful SRE assistant."

    def _init_provider(self):
        """Initialize the selected LLM provider."""
        print(f"{Fore.CYAN}[System] Using LLM provider: {self.provider_name}{Style.RESET_ALL}")

        if self.provider_name == "gemini":
            return GeminiProvider()
        elif self.provider_name in ("openai", "deepseek", "zlm"):
            return OpenAIProvider()
        else:
            raise ValueError(
                f"Unknown LLM_PROVIDER: {self.provider_name}. "
                f"Supported: 'gemini', 'openai', 'deepseek', 'zlm'"
            )

    def chat(self, user_input: str) -> str:
        """
        Process a user message through the ReAct loop.

        Includes sliding-window history truncation:
          - Keeps system prompt intact (handled by providers)
          - Prunes oldest user/assistant turns if history > MAX_HISTORY_MESSAGES
          - Ensures trimmed history starts with a user message (no orphaned assistant msgs)
        """
        self.conversation_history.append({
            "role": "user",
            "content": user_input,
        })

        # ---- Sliding window: truncate to last N messages ----
        # Drop oldest messages in user→assistant pairs to keep context coherent.
        if len(self.conversation_history) > MAX_HISTORY_MESSAGES:
            trimmed = self.conversation_history[-MAX_HISTORY_MESSAGES:]
            # Strip any leading non-user messages (tool results, orphaned assistant)
            while trimmed and trimmed[0]["role"] != "user":
                trimmed.pop(0)
            # Safety: if aggressive trimming killed everything, keep last user msg
            if not trimmed:
                trimmed = [self.conversation_history[-1]]
            self.conversation_history = trimmed

        print(f"{Fore.MAGENTA}  [Agent is thinking...]{Style.RESET_ALL}")

        try:
            response, tool_log = self.provider.chat(
                self.conversation_history,
                self.system_prompt,
            )
        except Exception as exc:
            response = f"I encountered an error communicating with the LLM: {exc}"
            tool_log = []
            print(f"{Fore.RED}  [LLM Error: {exc}]{Style.RESET_ALL}")

        # ---- Persist tool exchange summary so the LLM remembers what it ran ----
        if tool_log:
            tools_summary = "; ".join(
                f"{t['tool']}({t['args']}) -> {t['result_length']} chars"
                for t in tool_log
            )
            self.conversation_history.append({
                "role": "assistant",
                "content": f"[Tool calls this turn: {tools_summary}]\n\n{response}",
            })
        else:
            self.conversation_history.append({
                "role": "assistant",
                "content": response,
            })

        return response


# ==============================================================
#  Smoke Test (updated for dict assertions)
# ==============================================================

def run_smoke_test():
    """Quick verification that all tools return dicts with the loaded logs."""
    print(f"\n{Fore.CYAN}{'=' * 60}")
    print("SMOKE TEST -- Verifying Phase 2 Tool Modules (dict outputs)")
    print(f"{'=' * 60}{Style.RESET_ALL}\n")

    store = get_store()
    passed = 0
    failed = 0

    tests = [
        ("detect_slow_requests",         lambda: detect_slow_requests(store, time_window="48h")),
        ("detect_slow_requests(payment)", lambda: detect_slow_requests(store, service="payment_api", threshold_ms=500, time_window="48h")),
        ("diagnose_latency_sources",     lambda: diagnose_latency_sources(store, time_window="24h", baseline_window="48h")),
        ("analyze_error_patterns",       lambda: analyze_error_patterns(store, time_window="48h")),
        ("analyze_error_patterns(err)",  lambda: analyze_error_patterns(store, group_by="error_type", time_window="48h")),
        ("check_resource_usage",         lambda: check_resource_usage(store, time_window="48h")),
        ("check_resource_usage(pay)",    lambda: check_resource_usage(store, service="payment_api", time_window="48h")),
        ("check_resource_usage(notif)",  lambda: check_resource_usage(store, service="notification_service", time_window="48h")),
        ("generate_latency_chart",       lambda: generate_latency_chart(store, service="payment_api", time_window="24h")),
        ("generate_error_heatmap",       lambda: generate_error_heatmap(store, time_window="48h")),
    ]

    for name, fn in tests:
        try:
            result = fn()
            assert isinstance(result, dict), f"Expected dict, got {type(result).__name__}"
            # Verify it's JSON-serializable
            json_str = json.dumps(result, default=str)
            assert len(json_str) > 50, "Result JSON too short"
            print(f"  {Fore.GREEN}PASS{Style.RESET_ALL}: {name} ({len(json_str)} chars JSON)")
            passed += 1
        except Exception as exc:
            print(f"  {Fore.RED}FAIL{Style.RESET_ALL}: {name} -- {exc}")
            traceback.print_exc()
            failed += 1

    print(f"\n{Fore.CYAN}{'=' * 60}")
    print(f"SMOKE TEST RESULTS: {passed}/{passed + failed} passed")
    print(f"{'=' * 60}{Style.RESET_ALL}\n")

    return 0 if failed == 0 else 1


# ==============================================================
#  Interactive CLI
# ==============================================================

BANNER = f"""
{Fore.CYAN}{'=' * 60}
  KazamSRE Agent -- Performance Monitoring Assistant
  Type your questions naturally. Type 'quit' or 'exit' to stop.
  Type 'clear' to reset conversation history.
{'=' * 60}{Style.RESET_ALL}
"""

SAMPLE_QUERIES = [
    "Check payment_api for slow requests",
    "Are there any errors in the notification service?",
    "Show me the resource health for charging_controller",
    "Find slow requests in payment_api then diagnose where the latency is coming from",
    "Is payment_api performance getting worse compared to baseline?",
]


def interactive_cli():
    """Run the interactive terminal loop."""
    print(BANNER)

    print(f"{Fore.CYAN}Sample queries you can try:{Style.RESET_ALL}")
    for i, q in enumerate(SAMPLE_QUERIES, 1):
        print(f"  {Fore.WHITE}{i}. {q}{Style.RESET_ALL}")
    print()

    try:
        agent = SREAgent()
    except Exception as exc:
        print(f"{Fore.RED}[Fatal] Could not initialize agent: {exc}{Style.RESET_ALL}")
        traceback.print_exc()
        print(f"\n{Fore.YELLOW}Tip: Copy .env.example to .env and set your API keys.{Style.RESET_ALL}")
        return 1

    while True:
        try:
            user_input = input(f"\n{Fore.GREEN}You > {Style.RESET_ALL}").strip()
        except (KeyboardInterrupt, EOFError):
            print(f"\n{Fore.CYAN}Goodbye!{Style.RESET_ALL}")
            break

        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit", "q"):
            print(f"{Fore.CYAN}Goodbye!{Style.RESET_ALL}")
            break
        if user_input.lower() == "clear":
            agent.conversation_history.clear()
            print(f"{Fore.CYAN}[Conversation history cleared]{Style.RESET_ALL}")
            continue

        response = agent.chat(user_input)

        print(f"\n{Fore.CYAN}{'- ' * 30}{Style.RESET_ALL}")
        print(f"{Fore.WHITE}{response}{Style.RESET_ALL}")
        print(f"{Fore.CYAN}{'- ' * 30}{Style.RESET_ALL}")

    return 0


# ==============================================================
#  Entry Point
# ==============================================================

if __name__ == "__main__":
    if "--smoke" in sys.argv:
        sys.exit(run_smoke_test())
    else:
        sys.exit(interactive_cli())
