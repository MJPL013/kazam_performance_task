"""
latency_analysis.py -- Slow-Request Detection & Latency Diagnosis
=================================================================
Tools: detect_slow_requests, diagnose_latency_sources

Phase 1 logic preserved identically; operates on a shared LogStore.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from typing import Dict, List, Optional

from utils.baseline_calculator import (
    median,
    parse_window_to_timedelta,
    percentile,
    severity_label,
)
from utils.log_parser import (
    EndpointLatencyProfile,
    LatencyBreakdown,
    LogEntry,
    LogStore,
    SlowRequest,
)


# ==================================================
#  TOOL 1 -- detect_slow_requests
# ==================================================

def detect_slow_requests(
    store: LogStore,
    service: Optional[str] = None,
    threshold_ms: float = 2000.0,
    time_window: str = "1h",
) -> str:
    """
    Find requests exceeding `threshold_ms` and produce an SRE report.

    Steps:
        1. Filter by service + time window.
        2. Exclude entries with no response time.
        3. Exclude fast failures from baseline calculation.
        4. Identify slow requests (> threshold).
        5. Group by endpoint/event and compute Median & P90.
        6. Assign severity vs overall baseline.
        7. Detect incident spike windows (3+ slow in 5min per endpoint).
    """
    pool = store.filter(service=service, time_window=time_window)

    # Only entries that have a measurable response time
    timed = [e for e in pool if e.effective_response_time_ms is not None]
    # Baseline excludes fast failures
    baseline_pool = store.exclude_fast_failures(timed)
    baseline_times = [e.effective_response_time_ms for e in baseline_pool]
    overall_baseline = median(baseline_times) if baseline_times else 0.0

    # Identify slow requests (from full timed pool, not just baseline)
    slow_entries = [
        e for e in timed if e.effective_response_time_ms > threshold_ms
    ]

    slow_requests: List[SlowRequest] = []
    for e in slow_entries:
        slow_requests.append(SlowRequest(
            timestamp=e.timestamp,
            service=e.service,
            endpoint_or_event=e.group_key,
            response_time_ms=e.effective_response_time_ms,
            threshold_ms=threshold_ms,
            db_query_time_ms=e.db_query_time_ms,
            external_api_time_ms=e.external_api_time_ms,
            app_logic_time_ms=e.app_logic_time_ms,
            unaccounted_ms=e.unaccounted_latency_ms,
            user_id=e.user_id,
        ))

    # Group by endpoint/event
    groups: Dict[str, List[LogEntry]] = defaultdict(list)
    for e in baseline_pool:
        groups[e.group_key].append(e)

    profiles: List[EndpointLatencyProfile] = []
    for key, group_entries in sorted(groups.items()):
        rts = [e.effective_response_time_ms for e in group_entries]
        slow_in_group = sum(1 for r in rts if r > threshold_ms)
        med = median(rts)
        profiles.append(EndpointLatencyProfile(
            group_key=key,
            request_count=len(rts),
            median_ms=round(med, 2),
            p90_ms=round(percentile(rts, 90), 2),
            max_ms=round(max(rts), 2),
            slow_count=slow_in_group,
            baseline_median_ms=round(overall_baseline, 2),
            severity=severity_label(med, overall_baseline),
        ))

    # ---- SRE ADDITION: Spike Window Detection ----
    spike_windows: List[str] = []
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
                spike_windows.append(
                    f"  Incident Window: {cluster[0].timestamp.isoformat()} to "
                    f"{cluster[-1].timestamp.isoformat()} - "
                    f"{len(cluster)} requests on {ep} peaking at {peak_ms:.0f}ms"
                )
                i = j
            else:
                i += 1

    # ---- Format SRE report ----
    svc_label = service or "all services"
    lines = [
        f"=== SLOW REQUEST REPORT ===",
        f"Service: {svc_label} | Window: {time_window} | Threshold: {threshold_ms}ms",
        f"Reference Time: {store.reference_time.isoformat()}",
        f"Total timed requests: {len(timed)} | Baseline (excl. fast failures): {len(baseline_pool)}",
        f"Overall baseline median: {overall_baseline:.1f}ms",
        f"Slow requests found: {len(slow_requests)}",
        "",
    ]

    if profiles:
        lines.append("-- Endpoint / Event Profiles --")
        for p in sorted(profiles, key=lambda x: x.median_ms, reverse=True):
            lines.append(
                f"  [{p.severity:8s}] {p.group_key:<45s} "
                f"Median: {p.median_ms:>8.1f}ms  P90: {p.p90_ms:>8.1f}ms  "
                f"Max: {p.max_ms:>8.1f}ms  Count: {p.request_count}  "
                f"Slow: {p.slow_count}"
            )
        lines.append("")

    if spike_windows:
        lines.append("-- Spike Windows Detected (3+ slow requests within 5 min) --")
        lines.extend(spike_windows)
        lines.append("")

    if slow_requests:
        lines.append("-- Top 10 Slowest Requests --")
        for sr in sorted(slow_requests, key=lambda x: x.response_time_ms, reverse=True)[:10]:
            breakdown = ""
            if sr.db_query_time_ms is not None:
                breakdown = (
                    f"  DB: {sr.db_query_time_ms:.0f}ms | "
                    f"Ext: {sr.external_api_time_ms:.0f}ms | "
                    f"App: {sr.app_logic_time_ms:.0f}ms | "
                    f"Unaccounted: {sr.unaccounted_ms:.0f}ms"
                )
            lines.append(
                f"  {sr.timestamp.isoformat()} | {sr.endpoint_or_event:<40s} "
                f"| {sr.response_time_ms:.0f}ms{breakdown}"
            )
    else:
        lines.append("No requests exceeded the threshold.")

    return "\n".join(lines)


# ==================================================
#  TOOL 2 -- diagnose_latency_sources
# ==================================================

def diagnose_latency_sources(
    store: LogStore,
    service: Optional[str] = None,
    endpoint: Optional[str] = None,
    time_window: str = "1h",
    baseline_window: str = "24h",
) -> str:
    """
    Break down latency into DB / External / App / Unaccounted
    for each endpoint group.  Compare to historical baseline.

    Disjoint baselines:
        current  = [ref - current_td, ref)
        baseline = [ref - baseline_td, ref - current_td)   (NO overlap)
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

    breakdowns: List[LatencyBreakdown] = []
    profiles: List[EndpointLatencyProfile] = []

    for key in sorted(set(list(current_groups.keys()) + list(baseline_groups.keys()))):
        c_entries = current_groups.get(key, [])
        b_entries = baseline_groups.get(key, [])

        if not c_entries:
            continue

        c_rts = [e.effective_response_time_ms for e in c_entries]
        b_rts = [e.effective_response_time_ms for e in b_entries] if b_entries else c_rts

        c_median = median(c_rts)
        b_median = median(b_rts)
        sev = severity_label(c_median, b_median)

        profiles.append(EndpointLatencyProfile(
            group_key=key,
            request_count=len(c_rts),
            median_ms=round(c_median, 2),
            p90_ms=round(percentile(c_rts, 90), 2),
            max_ms=round(max(c_rts), 2),
            slow_count=0,
            baseline_median_ms=round(b_median, 2),
            severity=sev,
        ))

        # Latency breakdown
        entries_with_breakdown = [
            e for e in c_entries if e.db_query_time_ms is not None
        ]
        if entries_with_breakdown:
            db_vals = [e.db_query_time_ms for e in entries_with_breakdown]
            ext_vals = [e.external_api_time_ms or 0 for e in entries_with_breakdown]
            app_vals = [e.app_logic_time_ms or 0 for e in entries_with_breakdown]
            unacc_vals = [e.unaccounted_latency_ms or 0 for e in entries_with_breakdown]
            total_vals = [e.effective_response_time_ms for e in entries_with_breakdown]

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

            breakdowns.append(LatencyBreakdown(
                group_key=key,
                total_median_ms=round(total_med, 2),
                db_median_ms=round(db_med, 2),
                external_median_ms=round(ext_med, 2),
                app_logic_median_ms=round(app_med, 2),
                unaccounted_median_ms=round(unacc_med, 2),
                primary_bottleneck=bottleneck,
                bottleneck_pct=bottleneck_pct,
            ))

    # ---- Format SRE report ----
    svc_label = service or "all services"
    ep_label = endpoint or "all endpoints"
    lines = [
        f"=== LATENCY SOURCE DIAGNOSIS ===",
        f"Service: {svc_label} | Endpoint: {ep_label}",
        f"Current Window: {time_window} [{current_start.isoformat()} to {current_end.isoformat()}]",
        f"Baseline Window: {baseline_window} [{baseline_start.isoformat()} to {baseline_end.isoformat()}] (disjoint)",
        f"Reference Time: {store.reference_time.isoformat()}",
        f"Entries analyzed (current): {len(current)} | Baseline: {len(baseline_all)}",
        "",
    ]

    if profiles:
        lines.append("-- Latency vs Baseline --")
        for p in sorted(profiles, key=lambda x: x.median_ms, reverse=True):
            delta = ""
            if p.baseline_median_ms and p.baseline_median_ms > 0:
                change = ((p.median_ms - p.baseline_median_ms) / p.baseline_median_ms) * 100
                delta = f"  Delta: {change:+.1f}%"
            lines.append(
                f"  [{p.severity:8s}] {p.group_key:<40s}  "
                f"Current P50: {p.median_ms:>8.1f}ms  P90: {p.p90_ms:>8.1f}ms  "
                f"Baseline P50: {p.baseline_median_ms:>8.1f}ms{delta}"
            )
        lines.append("")

    if breakdowns:
        lines.append("-- Component Breakdown (Medians) --")
        for bd in sorted(breakdowns, key=lambda x: x.total_median_ms, reverse=True):
            lines.append(f"  {bd.group_key}:")
            lines.append(
                f"    Total: {bd.total_median_ms:.1f}ms -> "
                f"DB: {bd.db_median_ms:.1f}ms | "
                f"External: {bd.external_median_ms:.1f}ms | "
                f"App: {bd.app_logic_median_ms:.1f}ms | "
                f"Network/Queue: {bd.unaccounted_median_ms:.1f}ms"
            )
            lines.append(
                f"    Primary Bottleneck: {bd.primary_bottleneck} "
                f"({bd.bottleneck_pct:.1f}% of total)"
            )
        lines.append("")

    if not profiles and not breakdowns:
        lines.append("No latency data available for the specified filters.")

    return "\n".join(lines)
