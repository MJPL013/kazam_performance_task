"""
error_analysis.py -- Error Pattern Analysis
============================================
Tool: analyze_error_patterns

Phase 1 logic preserved identically; operates on a shared LogStore.
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from typing import Dict, List, Optional

from utils.log_parser import (
    ErrorBucket,
    LogEntry,
    LogStore,
    WarnStressSignal,
)


# ==================================================
#  TOOL 3 -- analyze_error_patterns
# ==================================================

def analyze_error_patterns(
    store: LogStore,
    service: Optional[str] = None,
    time_window: str = "1h",
    group_by: str = "endpoint",
) -> str:
    """
    Differentiate client (4xx) vs server (5xx) errors, track retries,
    compute failure rates, and detect WARN-log stress signals.

    BUG FIX: failure_rate_pct uses per-group denominator.
    group_by: 'endpoint' | 'error_type' | 'event_type'
    """
    pool = store.filter(service=service, time_window=time_window)
    total_count = len(pool)

    # Errors: WARN + ERROR level entries, or entries with status >= 400
    error_entries = [
        e for e in pool
        if e.level in ("WARN", "ERROR") or (e.status_code and e.status_code >= 400)
    ]

    # Group function
    def _key(e: LogEntry) -> str:
        if group_by == "error_type":
            return e.error_message or "unknown_error"
        elif group_by == "event_type":
            return e.event_type
        else:
            return e.group_key

    # BUG FIX: Per-group total for correct denominator
    total_per_group: Dict[str, int] = Counter(_key(e) for e in pool)

    buckets: Dict[str, ErrorBucket] = {}
    for e in error_entries:
        k = _key(e)
        if k not in buckets:
            buckets[k] = ErrorBucket(group_key=k, total_errors=0)
        b = buckets[k]
        b.total_errors += 1
        if e.is_client_error:
            b.client_errors += 1
        if e.is_server_error:
            b.server_errors += 1
        if e.error_message:
            b.error_types[e.error_message] = b.error_types.get(e.error_message, 0) + 1
        b.retry_total += e.retry_count

    # Failure rates & affected users
    affected_users_per_bucket: Dict[str, set] = defaultdict(set)
    for e in error_entries:
        k = _key(e)
        uid = e.user_id or e.metadata.get("recipient")
        if uid:
            affected_users_per_bucket[k].add(uid)

    for k, b in buckets.items():
        group_total = total_per_group.get(k, 0)
        b.failure_rate_pct = round(b.total_errors / group_total * 100, 2) if group_total else 0.0
        b.affected_users = len(affected_users_per_bucket.get(k, set()))

    # WARN-level stress signals
    warn_entries = [e for e in pool if e.level == "WARN"]
    warn_groups: Dict[str, List[LogEntry]] = defaultdict(list)
    for e in warn_entries:
        warn_groups[e.event_type].append(e)

    stress_signals: List[WarnStressSignal] = []
    for evt, entries in warn_groups.items():
        retries = [e.retry_count for e in entries if e.retry_count > 0]
        sample_errors = list(set(
            e.error_message for e in entries if e.error_message
        ))[:5]
        stress_signals.append(WarnStressSignal(
            service=entries[0].service,
            event_type=evt,
            count=len(entries),
            avg_retry_count=round(statistics.mean(retries), 2) if retries else 0.0,
            max_retry_count=max(retries) if retries else 0,
            sample_errors=sample_errors,
        ))

    # ---- Format SRE report ----
    svc_label = service or "all services"
    lines = [
        f"=== ERROR PATTERN REPORT ===",
        f"Service: {svc_label} | Window: {time_window} | Group By: {group_by}",
        f"Reference Time: {store.reference_time.isoformat()}",
        f"Total log entries in window: {total_count}",
        f"Error/Warn entries: {len(error_entries)} "
        f"({len(error_entries)/total_count*100:.1f}%)" if total_count else "No entries",
        "",
    ]

    if buckets:
        lines.append("-- Error Breakdown (failure_rate = errors / group total) --")
        for b in sorted(buckets.values(), key=lambda x: x.total_errors, reverse=True):
            grp_total = total_per_group.get(b.group_key, 0)
            lines.append(
                f"  {b.group_key:<45s}  Total: {b.total_errors:>4d}/{grp_total:<4d}  "
                f"4xx: {b.client_errors:>3d}  5xx: {b.server_errors:>3d}  "
                f"Retries: {b.retry_total:>3d}  "
                f"Failure Rate: {b.failure_rate_pct:>5.2f}%  "
                f"Affected Users: {b.affected_users}"
            )
            if b.error_types:
                for etype, cnt in sorted(b.error_types.items(), key=lambda x: x[1], reverse=True):
                    lines.append(f"      -- {etype}: {cnt}")
        lines.append("")

    if stress_signals:
        lines.append("-- WARN Stress Signals (Pre-Error Indicators) --")
        for s in sorted(stress_signals, key=lambda x: x.count, reverse=True):
            lines.append(
                f"  {s.event_type:<35s}  Count: {s.count:>4d}  "
                f"Avg Retries: {s.avg_retry_count:.1f}  "
                f"Max Retries: {s.max_retry_count}"
            )
            if s.sample_errors:
                lines.append(f"      Errors: {', '.join(s.sample_errors)}")
    else:
        lines.append("No WARN-level stress signals detected.")

    return "\n".join(lines)
