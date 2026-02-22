"""
latency_analysis.py -- Slow-Request Detection & Latency Diagnosis
=================================================================
Tools: detect_slow_requests, diagnose_latency_sources

REFACTORED: Returns structured dicts (not ASCII strings).
            Uses tuple() for cached median/percentile calls.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from typing import Any, Dict, List, Optional

from utils.baseline_calculator import (
    median,
    parse_window_to_timedelta,
    percentile,
    severity_label,
)
from utils.log_parser import LogEntry, LogStore


# ==================================================
#  TOOL 1 -- detect_slow_requests
# ==================================================

def detect_slow_requests(
    store: LogStore,
    service: Optional[str] = None,
    threshold_ms: float = 2000.0,
    time_window: str = "1h",
) -> dict:
    """
    Find requests exceeding `threshold_ms`.

    Returns a structured dict with:
      - summary metadata (service, window, threshold, counts)
      - endpoint/event profiles with P50/P90/severity
      - spike windows (3+ slow reqs within 5 min)
      - top 10 slowest requests with latency breakdown
    """
    pool = store.filter(service=service, time_window=time_window)

    # Only entries that have a measurable response time
    timed = [e for e in pool if e.effective_response_time_ms is not None]
    # Baseline excludes fast failures
    baseline_pool = store.exclude_fast_failures(timed)
    baseline_times = tuple(e.effective_response_time_ms for e in baseline_pool)
    overall_baseline = median(baseline_times) if baseline_times else 0.0

    # Identify slow requests (from full timed pool, not just baseline)
    slow_entries = [
        e for e in timed if e.effective_response_time_ms > threshold_ms
    ]

    # Build slow request records
    slow_requests: List[Dict[str, Any]] = []
    for e in slow_entries:
        slow_requests.append({
            "timestamp": e.timestamp.isoformat(),
            "service": e.service,
            "endpoint_or_event": e.group_key,
            "response_time_ms": round(e.effective_response_time_ms, 2),
            "threshold_ms": threshold_ms,
            "db_query_time_ms": round(e.db_query_time_ms, 2) if e.db_query_time_ms is not None else None,
            "external_api_time_ms": round(e.external_api_time_ms, 2) if e.external_api_time_ms is not None else None,
            "app_logic_time_ms": round(e.app_logic_time_ms, 2) if e.app_logic_time_ms is not None else None,
            "unaccounted_ms": round(e.unaccounted_latency_ms, 2) if e.unaccounted_latency_ms is not None else None,
            "user_id": e.user_id,
        })

    # Group by endpoint/event for profiles
    groups: Dict[str, List[LogEntry]] = defaultdict(list)
    for e in baseline_pool:
        groups[e.group_key].append(e)

    profiles: List[Dict[str, Any]] = []
    for key, group_entries in sorted(groups.items()):
        rts = tuple(e.effective_response_time_ms for e in group_entries)
        slow_in_group = sum(1 for r in rts if r > threshold_ms)
        med = median(rts)
        profiles.append({
            "group_key": key,
            "request_count": len(rts),
            "median_ms": round(med, 2),
            "p90_ms": round(percentile(rts, 90), 2),
            "max_ms": round(max(rts), 2),
            "slow_count": slow_in_group,
            "baseline_median_ms": round(overall_baseline, 2),
            "severity": severity_label(med, overall_baseline),
        })

    # ---- Spike Window Detection ----
    spike_windows: List[Dict[str, Any]] = []
    slow_by_endpoint: Dict[str, List[LogEntry]] = defaultdict(list)
    for e in slow_entries:
        slow_by_endpoint[e.group_key].append(e)

    for ep, ep_entries in sorted(slow_by_endpoint.items()):
        sorted_entries = sorted(ep_entries, key=lambda x: x.timestamp)
        i = 0
        while i < len(sorted_entries):
            cluster = [sorted_entries[i]]
            j = i + 1
            window_end = sorted_entries[i].timestamp + timedelta(minutes=5)
            while j < len(sorted_entries) and sorted_entries[j].timestamp <= window_end:
                cluster.append(sorted_entries[j])
                j += 1
            if len(cluster) >= 3:
                peak_ms = max(e.effective_response_time_ms for e in cluster)
                spike_windows.append({
                    "start": cluster[0].timestamp.isoformat(),
                    "end": cluster[-1].timestamp.isoformat(),
                    "endpoint": ep,
                    "count": len(cluster),
                    "peak_ms": round(peak_ms, 2),
                })
                i = j
            else:
                i += 1

    # Sort slow requests by response time descending, take top 10
    top_slow = sorted(slow_requests, key=lambda x: x["response_time_ms"], reverse=True)[:10]

    return {
        "data_context": store.get_data_context(),
        "service": service or "all_services",
        "time_window": time_window,
        "threshold_ms": threshold_ms,
        "reference_time": store.reference_time.isoformat(),
        "total_timed_requests": len(timed),
        "baseline_pool_size": len(baseline_pool),
        "baseline_median_ms": round(overall_baseline, 2),
        "slow_request_count": len(slow_requests),
        "profiles": profiles,
        "spike_windows": spike_windows,
        "top_slow_requests": top_slow,
    }


# ==================================================
#  TOOL 2 -- diagnose_latency_sources
# ==================================================

def diagnose_latency_sources(
    store: LogStore,
    service: Optional[str] = None,
    endpoint: Optional[str] = None,
    time_window: str = "1h",
    baseline_window: str = "24h",
) -> dict:
    """
    Break down latency into DB / External / App / Unaccounted
    for each endpoint group.  Compare to historical baseline.

    Disjoint baselines:
        current  = [ref - current_td, ref)
        baseline = [ref - baseline_td, ref - current_td)   (NO overlap)

    Returns structured dict with profiles and component breakdowns.
    """
    current_td = parse_window_to_timedelta(time_window)
    baseline_td = parse_window_to_timedelta(baseline_window)

    current_start = store.reference_time - current_td
    current_end = store.reference_time

    # Disjoint baseline
    baseline_start = store.reference_time - baseline_td
    baseline_end = current_start

    # Current window
    current = store.filter_range(current_start, current_end, service=service, endpoint=endpoint)
    current = store.exclude_fast_failures(current)
    current = [e for e in current if e.effective_response_time_ms is not None]

    # Baseline window (disjoint)
    baseline_all = store.filter_range(baseline_start, baseline_end, service=service, endpoint=endpoint)
    baseline_all = store.exclude_fast_failures(baseline_all)
    baseline_all = [e for e in baseline_all if e.effective_response_time_ms is not None]

    # Group both
    def _group(entries: List[LogEntry]) -> Dict[str, List[LogEntry]]:
        g: Dict[str, List[LogEntry]] = defaultdict(list)
        for e in entries:
            g[e.group_key].append(e)
        return g

    current_groups = _group(current)
    baseline_groups = _group(baseline_all)

    profiles: List[Dict[str, Any]] = []
    breakdowns: List[Dict[str, Any]] = []

    for key in sorted(set(list(current_groups.keys()) + list(baseline_groups.keys()))):
        c_entries = current_groups.get(key, [])
        b_entries = baseline_groups.get(key, [])

        if not c_entries:
            continue

        c_rts = tuple(e.effective_response_time_ms for e in c_entries)
        b_rts = tuple(e.effective_response_time_ms for e in b_entries) if b_entries else c_rts

        c_median = median(c_rts)
        b_median = median(b_rts)
        sev = severity_label(c_median, b_median)

        # Delta percentage
        delta_pct = None
        if b_median and b_median > 0:
            delta_pct = round(((c_median - b_median) / b_median) * 100, 1)

        profiles.append({
            "group_key": key,
            "request_count": len(c_rts),
            "current_median_ms": round(c_median, 2),
            "current_p90_ms": round(percentile(c_rts, 90), 2),
            "current_max_ms": round(max(c_rts), 2),
            "baseline_median_ms": round(b_median, 2),
            "delta_pct": delta_pct,
            "severity": sev,
        })

        # Latency breakdown
        entries_with_breakdown = [
            e for e in c_entries if e.db_query_time_ms is not None
        ]
        if entries_with_breakdown:
            db_vals = tuple(e.db_query_time_ms for e in entries_with_breakdown)
            ext_vals = tuple(e.external_api_time_ms or 0 for e in entries_with_breakdown)
            app_vals = tuple(e.app_logic_time_ms or 0 for e in entries_with_breakdown)
            unacc_vals = tuple(e.unaccounted_latency_ms or 0 for e in entries_with_breakdown)
            total_vals = tuple(e.effective_response_time_ms for e in entries_with_breakdown)

            db_med = median(db_vals)
            ext_med = median(ext_vals)
            app_med = median(app_vals)
            unacc_med = median(unacc_vals)
            total_med = median(total_vals)

            components = {
                "Database": db_med,
                "External API": ext_med,
                "App Logic": app_med,
                "Network/Queue": unacc_med,
            }
            bottleneck = max(components, key=components.get)
            bottleneck_pct = (
                round(components[bottleneck] / total_med * 100, 1)
                if total_med > 0 else 0.0
            )

            breakdowns.append({
                "group_key": key,
                "total_median_ms": round(total_med, 2),
                "db_median_ms": round(db_med, 2),
                "external_median_ms": round(ext_med, 2),
                "app_logic_median_ms": round(app_med, 2),
                "unaccounted_median_ms": round(unacc_med, 2),
                "primary_bottleneck": bottleneck,
                "bottleneck_pct": bottleneck_pct,
            })

    return {
        "data_context": store.get_data_context(),
        "service": service or "all_services",
        "endpoint": endpoint or "all_endpoints",
        "current_window": {
            "label": time_window,
            "start": current_start.isoformat(),
            "end": current_end.isoformat(),
            "entries_analyzed": len(current),
        },
        "baseline_window": {
            "label": baseline_window,
            "start": baseline_start.isoformat(),
            "end": baseline_end.isoformat(),
            "entries_analyzed": len(baseline_all),
        },
        "reference_time": store.reference_time.isoformat(),
        "profiles": profiles,
        "breakdowns": breakdowns,
    }
