"""
resource_monitoring.py -- Resource Usage & Health Indicators
============================================================
Tool: check_resource_usage

Phase 1 logic preserved identically; operates on a shared LogStore.
Includes all SRE additions:
  - Strict Error Rate (ERROR/5xx only)
  - Separate Warn/Throttle Rate
  - Connection Pool Exhaustion scanning
  - Queue Depth / Backlog with Burn Rate
  - Missing-index note extraction
"""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Optional

from utils.baseline_calculator import median, percentile
from utils.log_parser import LogEntry, LogStore, ResourceHealthIndicator


# ==================================================
#  TOOL 4 -- check_resource_usage
# ==================================================

def check_resource_usage(
    store: LogStore,
    service: Optional[str] = None,
    time_window: str = "1h",
) -> str:
    """
    Monitor resource-health proxies (no actual CPU/mem in logs).

    For each service:
    - payment_api:          DB slowdowns, external API timeouts, connection pool,
                            missing index notes, error & warn rates
    - charging_controller:  Hardware errors, session failures, state anomalies
    - notification_service: Queue delays, queue depth/backlog, retry exhaustion,
                            delivery failures

    BUG FIX: "Error Rate" = ERROR level or status >= 500 only.
             Separate "Warn/Throttle Rate" for WARN level.
    """
    pool = store.filter(service=service, time_window=time_window)
    total = len(pool)

    indicators: List[ResourceHealthIndicator] = []

    # ---- Group by service ----
    by_service: Dict[str, List[LogEntry]] = defaultdict(list)
    for e in pool:
        by_service[e.service].append(e)

    for svc, entries in sorted(by_service.items()):
        svc_total = len(entries)

        # Strict Error Rate -- only ERROR level or 5xx
        strict_errors = [
            e for e in entries
            if e.level == "ERROR" or (e.status_code is not None and e.status_code >= 500)
        ]
        error_rate = len(strict_errors) / svc_total * 100 if svc_total else 0.0
        indicators.append(ResourceHealthIndicator(
            service=svc,
            indicator_name="Error Rate",
            current_value=round(error_rate, 2),
            severity=("CRITICAL" if error_rate > 15
                      else "HIGH" if error_rate > 10
                      else "MEDIUM" if error_rate > 5
                      else "NORMAL"),
            detail=f"{len(strict_errors)}/{svc_total} entries (ERROR/5xx only)",
        ))

        # Separate Warn/Throttle Rate
        warns = [e for e in entries if e.level == "WARN"]
        warn_rate = len(warns) / svc_total * 100 if svc_total else 0.0
        indicators.append(ResourceHealthIndicator(
            service=svc,
            indicator_name="Warn/Throttle Rate",
            current_value=round(warn_rate, 2),
            severity=("HIGH" if warn_rate > 20
                      else "MEDIUM" if warn_rate > 10
                      else "NORMAL"),
            detail=f"{len(warns)}/{svc_total} entries (WARN only)",
        ))

        # ---- Service-specific indicators ----

        if svc == "payment_api":
            # DB slow queries + missing index note extraction
            db_slow = [
                e for e in entries
                if e.event_type == "database_query_slow"
            ]
            missing_index_count = sum(
                1 for e in db_slow
                if e.metadata.get("note", "").find("missing_index_suspected") >= 0
            )
            detail = f"database_query_slow events: {len(db_slow)}"
            if missing_index_count > 0:
                detail += f" (missing_index_suspected: {missing_index_count})"
            indicators.append(ResourceHealthIndicator(
                service=svc,
                indicator_name="DB Slow Queries",
                current_value=float(len(db_slow)),
                severity="HIGH" if len(db_slow) > 10 else "MEDIUM" if len(db_slow) > 3 else "NORMAL",
                detail=detail,
            ))

            # External API timeouts
            ext_timeout = [
                e for e in entries
                if e.event_type == "external_api_timeout"
            ]
            indicators.append(ResourceHealthIndicator(
                service=svc,
                indicator_name="External API Timeouts",
                current_value=float(len(ext_timeout)),
                severity="HIGH" if len(ext_timeout) > 5 else "MEDIUM" if len(ext_timeout) > 1 else "NORMAL",
                detail=f"external_api_timeout events: {len(ext_timeout)}",
            ))

            # Connection Pool Exhaustion
            conn_pool_hits = [
                e for e in entries
                if "connection from pool" in str(e.metadata.get("stack_trace", "")).lower()
            ]
            pool_sev = ("CRITICAL" if len(conn_pool_hits) > 5
                        else "HIGH" if len(conn_pool_hits) > 2
                        else "NORMAL")
            indicators.append(ResourceHealthIndicator(
                service=svc,
                indicator_name="DB Connection Pool Exhaustion",
                current_value=float(len(conn_pool_hits)),
                severity=pool_sev,
                detail=f"stack_trace mentions 'connection from pool': {len(conn_pool_hits)}",
            ))

        elif svc == "charging_controller":
            # Hardware communication errors
            hw_err = [
                e for e in entries
                if e.event_type == "hardware_communication_error"
            ]
            indicators.append(ResourceHealthIndicator(
                service=svc,
                indicator_name="Hardware Errors",
                current_value=float(len(hw_err)),
                severity="CRITICAL" if len(hw_err) > 10 else "HIGH" if len(hw_err) > 5 else "NORMAL",
                detail=f"hardware_communication_error events: {len(hw_err)}",
            ))

            # Session failure ratio
            started = sum(1 for e in entries if e.event_type == "charging_session_started")
            completed = sum(1 for e in entries if e.event_type == "charging_session_completed")
            if started > 0:
                completion_rate = completed / started * 100
                indicators.append(ResourceHealthIndicator(
                    service=svc,
                    indicator_name="Session Completion Rate",
                    current_value=round(completion_rate, 1),
                    severity="HIGH" if completion_rate < 70 else "MEDIUM" if completion_rate < 85 else "NORMAL",
                    detail=f"Completed: {completed}/{started} sessions",
                ))

        elif svc == "notification_service":
            # Queue wait times
            queue_times = [
                e.queue_wait_time_ms
                for e in entries
                if e.queue_wait_time_ms is not None
            ]
            if queue_times:
                q_median = median(queue_times)
                q_p90 = percentile(queue_times, 90)
                indicators.append(ResourceHealthIndicator(
                    service=svc,
                    indicator_name="Queue Wait Time (P50)",
                    current_value=round(q_median, 1),
                    severity="HIGH" if q_median > 300 else "MEDIUM" if q_median > 150 else "NORMAL",
                    detail=f"Median: {q_median:.1f}ms, P90: {q_p90:.1f}ms",
                ))

            # Queue Depth / Backlog Indicator
            queue_depth_entries = [
                e for e in entries
                if e.metadata.get("queue_depth") is not None
            ]
            if queue_depth_entries:
                depths = [float(e.metadata["queue_depth"]) for e in queue_depth_entries]
                max_depth = max(depths)
                latest_depth_entry = max(queue_depth_entries, key=lambda e: e.timestamp)
                latest_depth = float(latest_depth_entry.metadata["queue_depth"])
                depth_sev = ("CRITICAL" if latest_depth > 1000
                             else "HIGH" if latest_depth > 300
                             else "MEDIUM" if latest_depth > 100
                             else "NORMAL")

                detail_str = f"Latest: {latest_depth:.0f}, Max: {max_depth:.0f}, Samples: {len(depths)}"

                # Backlog Burn Rate
                rate = latest_depth_entry.metadata.get("processing_rate_per_sec")
                if rate and float(rate) > 0:
                    burn_seconds = latest_depth / float(rate)
                    detail_str += f", Backlog Burn Rate: {burn_seconds:.0f}s to clear ({float(rate)}/sec)"

                indicators.append(ResourceHealthIndicator(
                    service=svc,
                    indicator_name="Queue Depth (Backlog)",
                    current_value=latest_depth,
                    severity=depth_sev,
                    detail=detail_str,
                ))

            # Retry exhaustion
            exhausted = [
                e for e in entries
                if e.retry_count > 0 and e.max_retries and e.retry_count >= e.max_retries
            ]
            indicators.append(ResourceHealthIndicator(
                service=svc,
                indicator_name="Retry Exhaustion",
                current_value=float(len(exhausted)),
                severity="HIGH" if len(exhausted) > 10 else "MEDIUM" if len(exhausted) > 3 else "NORMAL",
                detail=f"Entries at max retries: {len(exhausted)}",
            ))

            # Delivery failures
            failed = [e for e in entries if e.event_type == "message_failed"]
            indicators.append(ResourceHealthIndicator(
                service=svc,
                indicator_name="Delivery Failures",
                current_value=float(len(failed)),
                severity="HIGH" if len(failed) > 10 else "MEDIUM" if len(failed) > 3 else "NORMAL",
                detail=f"message_failed events: {len(failed)}",
            ))

    # ---- Format SRE report ----
    svc_label = service or "all services"
    lines = [
        f"=== RESOURCE USAGE / HEALTH REPORT ===",
        f"Service: {svc_label} | Window: {time_window}",
        f"Reference Time: {store.reference_time.isoformat()}",
        f"Total entries in window: {total}",
        "",
    ]

    crit = [i for i in indicators if i.severity == "CRITICAL"]
    high = [i for i in indicators if i.severity == "HIGH"]

    if crit:
        lines.append("CRITICAL Issues:")
        for i in crit:
            lines.append(f"  * [{i.service}] {i.indicator_name}: {i.current_value} -- {i.detail}")
        lines.append("")

    if high:
        lines.append("HIGH Issues:")
        for i in high:
            lines.append(f"  * [{i.service}] {i.indicator_name}: {i.current_value} -- {i.detail}")
        lines.append("")

    lines.append("-- Full Indicator Table --")
    for i in sorted(indicators, key=lambda x: (x.service, x.indicator_name)):
        sev_map = {"CRITICAL": "[!!]", "HIGH": "[! ]", "MEDIUM": "[. ]", "NORMAL": "[  ]"}
        sev_icon = sev_map.get(i.severity, "[  ]")
        lines.append(
            f"  {sev_icon} [{i.severity:8s}] {i.service:<25s} "
            f"{i.indicator_name:<35s}  Value: {i.current_value}  "
            f"| {i.detail}"
        )

    return "\n".join(lines)
