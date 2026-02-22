"""
error_analysis.py -- Error Pattern Analysis
============================================
Tool: analyze_error_patterns

REFACTORED: Returns structured dict (not ASCII string).
            Uses tuple() for cached median/percentile calls.
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional

from utils.log_parser import LogEntry, LogStore


# ==================================================
#  Helpers
# ==================================================

def _is_request_event(e: LogEntry) -> bool:
    """True if this entry represents an actual request (not a pure info/lifecycle log)."""
    return (
        e.method is not None
        or e.response_time_ms is not None
        or e.metadata.get("processing_time_ms") is not None
        or e.metadata.get("response_time_ms") is not None
        or (e.status_code is not None)
    )


# ==================================================
#  TOOL 3 -- analyze_error_patterns
# ==================================================

def analyze_error_patterns(
    store: LogStore,
    service: Optional[str] = None,
    time_window: str = "1h",
    group_by: str = "endpoint",
) -> dict:
    """
    Differentiate client (4xx) vs server (5xx) errors, track retries,
    compute failure rates, and detect WARN-log stress signals.

    BUG FIX: failure_rate_pct uses per-group denominator.
    group_by: 'endpoint' | 'error_type' | 'event_type' | 'provider'

    Returns structured dict with buckets and stress signals.
    """
    pool = store.filter(service=service, time_window=time_window)
    total_count = len(pool)

    # Errors: ERROR level, status >= 400, final_status=="failed",
    #         or WARN-with-server-error (status >= 500).
    # Plain WARNs without 5xx are NOT errors -- they live in stress_signals.
    error_entries = [
        e for e in pool
        if e.level == "ERROR"
        or (e.level == "WARN" and e.status_code is not None and e.status_code >= 500)
        or (e.status_code is not None and e.status_code >= 400)
        or e.metadata.get("final_status") == "failed"
    ]

    # Group function
    def _key(e: LogEntry) -> str:
        if group_by == "error_type":
            return e.error_message or "unknown_error"
        elif group_by == "event_type":
            return e.event_type
        elif group_by == "provider":
            return e.metadata.get("provider", "unknown_provider")
        else:
            return e.group_key

    # BUG FIX: Per-group total for correct denominator
    # When group_by="provider", only count entries that actually have a provider field.
    if group_by == "provider":
        provider_pool = [e for e in pool if e.metadata.get("provider")]
        total_per_group: Dict[str, int] = Counter(_key(e) for e in provider_pool)
    else:
        total_per_group: Dict[str, int] = Counter(_key(e) for e in pool)

    # Build error buckets
    buckets_raw: Dict[str, Dict[str, Any]] = {}
    for e in error_entries:
        k = _key(e)
        if k not in buckets_raw:
            buckets_raw[k] = {
                "group_key": k,
                "total_errors": 0,
                "client_errors": 0,
                "server_errors": 0,
                "error_types": {},
                "retry_total": 0,
                "failure_rate_pct": 0.0,
                "affected_users": 0,
            }
        b = buckets_raw[k]
        b["total_errors"] += 1
        if e.is_client_error:
            b["client_errors"] += 1
        if e.is_server_error:
            b["server_errors"] += 1
        if e.error_message:
            b["error_types"][e.error_message] = b["error_types"].get(e.error_message, 0) + 1
        b["retry_total"] += e.retry_count

    # Failure rates & affected users
    affected_users_per_bucket: Dict[str, set] = defaultdict(set)
    for e in error_entries:
        k = _key(e)
        uid = e.user_id or e.metadata.get("recipient")
        if uid:
            affected_users_per_bucket[k].add(uid)

    for k, b in buckets_raw.items():
        group_total = total_per_group.get(k, 0)
        b["failure_rate_pct"] = round(b["total_errors"] / group_total * 100, 2) if group_total else 0.0
        b["affected_users"] = len(affected_users_per_bucket.get(k, set()))

    # Sort buckets by total errors descending
    buckets = sorted(buckets_raw.values(), key=lambda x: x["total_errors"], reverse=True)

    # WARN-level stress signals
    warn_entries = [e for e in pool if e.level == "WARN"]
    warn_groups: Dict[str, List[LogEntry]] = defaultdict(list)
    for e in warn_entries:
        warn_groups[e.event_type].append(e)

    stress_signals: List[Dict[str, Any]] = []
    for evt, entries in warn_groups.items():
        retries = [e.retry_count for e in entries if e.retry_count > 0]
        sample_errors = list(set(
            e.error_message for e in entries if e.error_message
        ))[:5]
        stress_signals.append({
            "service": entries[0].service,
            "event_type": evt,
            "count": len(entries),
            "avg_retry_count": round(statistics.mean(retries), 2) if retries else 0.0,
            "max_retry_count": max(retries) if retries else 0,
            "sample_errors": sample_errors,
        })

    # Sort stress signals by count descending
    stress_signals.sort(key=lambda x: x["count"], reverse=True)

    # Request-only count for accurate failure rate denominator
    request_count = sum(1 for e in pool if _is_request_event(e))

    return {
        "data_context": store.get_data_context(),
        "service": service or "all_services",
        "time_window": time_window,
        "group_by": group_by,
        "reference_time": store.reference_time.isoformat(),
        "total_entries_in_window": total_count,
        "request_entries": request_count,
        "error_warn_entries": len(error_entries),
        "error_rate_pct": round(len(error_entries) / request_count * 100, 2) if request_count else 0.0,
        "buckets": buckets,
        "stress_signals": stress_signals,
    }
