"""
agent.py -- Multi-Model SRE Agent Orchestrator
===============================================
ReAct loop with function calling, supporting:
  - Google Gemini  (native SDK)
  - OpenAI-compatible APIs  (DeepSeek, ZLM, local models)

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
    return _store


# ── Tool wrapper functions (bridge between LLM args and tool modules) ──

def tool_detect_slow_requests(
    service: Optional[str] = None,
    threshold_ms: float = 2000.0,
    time_window: str = "1h",
) -> str:
    return detect_slow_requests(get_store(), service=service, threshold_ms=threshold_ms, time_window=time_window)


def tool_diagnose_latency_sources(
    service: Optional[str] = None,
    endpoint: Optional[str] = None,
    time_window: str = "1h",
    baseline_window: str = "24h",
) -> str:
    return diagnose_latency_sources(get_store(), service=service, endpoint=endpoint, time_window=time_window, baseline_window=baseline_window)


def tool_analyze_error_patterns(
    service: Optional[str] = None,
    time_window: str = "1h",
    group_by: str = "endpoint",
) -> str:
    return analyze_error_patterns(get_store(), service=service, time_window=time_window, group_by=group_by)


def tool_check_resource_usage(
    service: Optional[str] = None,
    time_window: str = "1h",
) -> str:
    return check_resource_usage(get_store(), service=service, time_window=time_window)


# ── Registry: name -> (function, JSON schema) ──

TOOL_FUNCTIONS: Dict[str, Callable] = {
    "detect_slow_requests": tool_detect_slow_requests,
    "diagnose_latency_sources": tool_diagnose_latency_sources,
    "analyze_error_patterns": tool_analyze_error_patterns,
    "check_resource_usage": tool_check_resource_usage,
}

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "detect_slow_requests",
            "description": "Find requests exceeding a latency threshold and identify incident spike windows. Returns an SRE-formatted report with endpoint profiles, P50/P90 stats, and Top 10 slowest requests.",
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
            "description": "Break down latency into DB, External API, App Logic, and Network/Queue components. Compares current window against a disjoint historical baseline to detect regressions. Identifies the primary bottleneck.",
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
            "description": "Analyze error distribution: differentiates 4xx vs 5xx, computes per-group failure rates, tracks retry patterns, and detects WARN-level pre-error stress signals.",
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
                        "enum": ["endpoint", "error_type", "event_type"],
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
            "description": "Monitor service health: error rates (strict ERROR/5xx), warn/throttle rates, DB connection pool exhaustion, queue depth with backlog burn rate, hardware errors, session completion rate, retry exhaustion, delivery failures, and missing DB index detection.",
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
]


def execute_tool(name: str, arguments: Dict[str, Any]) -> str:
    """Execute a tool by name with the given arguments."""
    func = TOOL_FUNCTIONS.get(name)
    if not func:
        return f"Error: Unknown tool '{name}'. Available: {list(TOOL_FUNCTIONS.keys())}"
    try:
        # Filter out None values so defaults are used
        clean_args = {k: v for k, v in arguments.items() if v is not None}
        return func(**clean_args)
    except Exception as exc:
        return f"Error executing {name}: {exc}\n{traceback.format_exc()}"


# ==============================================================
#  LLM Providers
# ==============================================================

MAX_TOOL_CALLS_PER_TURN = 4


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
        """Run the ReAct loop with Gemini."""
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
                return "\n".join(text_parts) if text_parts else "I could not generate a response."

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
                        f"{', '.join(f'{k}={v!r}' for k, v in args.items())})]"
                        f"{Style.RESET_ALL}"
                    )

                    result = execute_tool(fc.name, args)

                    # Truncate very long results for display
                    display_result = result[:500] + "..." if len(result) > 500 else result
                    print(f"{Fore.BLUE}  [Tool Result: {len(result)} chars]{Style.RESET_ALL}")

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

        return "I've reached the maximum number of tool calls for this turn. Please refine your question."


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

    def chat(self, messages: List[Dict], system_prompt: str) -> str:
        """Run the ReAct loop with OpenAI-compatible API."""
        full_messages = [{"role": "system", "content": system_prompt}] + messages

        tool_call_count = 0

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
                return choice.message.content or "I could not generate a response."

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
                    f"{', '.join(f'{k}={v!r}' for k, v in args.items())})]"
                    f"{Style.RESET_ALL}"
                )

                result = execute_tool(func_name, args)
                print(f"{Fore.BLUE}  [Tool Result: {len(result)} chars]{Style.RESET_ALL}")

                full_messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })

        return "I've reached the maximum number of tool calls for this turn. Please refine your question."


# ==============================================================
#  Agent Class
# ==============================================================

class SREAgent:
    """Multi-model SRE agent with ReAct loop."""

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

        1. Add user message to conversation history
        2. Call the LLM provider (which handles tool calling internally)
        3. Add assistant response to history
        4. Return the final response
        """
        self.conversation_history.append({
            "role": "user",
            "content": user_input,
        })

        print(f"{Fore.MAGENTA}  [Agent is thinking...]{Style.RESET_ALL}")

        try:
            response = self.provider.chat(
                self.conversation_history,
                self.system_prompt,
            )
        except Exception as exc:
            response = f"I encountered an error communicating with the LLM: {exc}"
            print(f"{Fore.RED}  [LLM Error: {exc}]{Style.RESET_ALL}")

        self.conversation_history.append({
            "role": "assistant",
            "content": response,
        })

        return response


# ==============================================================
#  Smoke Test
# ==============================================================

def run_smoke_test():
    """Quick verification that all tools work with the loaded logs."""
    print(f"\n{Fore.CYAN}{'=' * 60}")
    print("SMOKE TEST -- Verifying Phase 2 Tool Modules")
    print(f"{'=' * 60}{Style.RESET_ALL}\n")

    store = get_store()
    passed = 0
    failed = 0

    tests = [
        ("detect_slow_requests",       lambda: detect_slow_requests(store, time_window="48h")),
        ("detect_slow_requests(payment)", lambda: detect_slow_requests(store, service="payment_api", threshold_ms=500, time_window="48h")),
        ("diagnose_latency_sources",   lambda: diagnose_latency_sources(store, time_window="24h", baseline_window="48h")),
        ("analyze_error_patterns",     lambda: analyze_error_patterns(store, time_window="48h")),
        ("analyze_error_patterns(err)", lambda: analyze_error_patterns(store, group_by="error_type", time_window="48h")),
        ("check_resource_usage",       lambda: check_resource_usage(store, time_window="48h")),
        ("check_resource_usage(pay)",  lambda: check_resource_usage(store, service="payment_api", time_window="48h")),
        ("check_resource_usage(notif)", lambda: check_resource_usage(store, service="notification_service", time_window="48h")),
    ]

    for name, fn in tests:
        try:
            result = fn()
            assert isinstance(result, str) and len(result) > 50, "Result too short"
            print(f"  {Fore.GREEN}PASS{Style.RESET_ALL}: {name} ({len(result)} chars)")
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
    "The system feels slow",
    "Are there any errors in the payment API?",
    "Show me the resource health across all services",
    "Find slow requests then diagnose where the latency is coming from",
    "Is performance getting worse compared to baseline?",
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
