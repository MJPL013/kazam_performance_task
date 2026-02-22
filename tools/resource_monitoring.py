"""
resource_monitoring.py -- Resource Usage & Health Indicators
============================================================
Tool: check_resource_usage

REFACTORED: Returns structured dict (not ASCII string).
  - Fixed connection pool check (pool exhausted / timeout waiting / no available)
  - Fixed missing index check (in-operator on note string)
  - Added charging_controller rich metrics:
      station error grouping, duration drift, energy anomalies
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Optional

from utils.baseline_calculator import median, percentile
from utils.log_parser import LogEntry, LogStore


# ==================================================
#  TOOL 4 -- check_resource_usage
# ==================================================

def check_resource_usage(
    store: LogStore,
    service: Optional[str] = None,
    time_window: str = "1h",
) -> dict:
    """
    Monitor resource-health proxies (no actual CPU/mem in logs).

    Returns a structured dict with per-service health indicators.
    """
    pool = store.filter(service=service, time_window=time_window)
    total = len(pool)

    indicators: List[Dict[str, Any]] = []

    # ---- Group by service ----
    by_service: Dict[str, List[LogEntry]] = defaultdict(list)
    for e in pool:
        by_service[e.service].append(e)

    for svc, entries in sorted(by_service.items()):
        svc_total = len(entries)

        # -- Strict Error Rate -- only ERROR level or 5xx --
        strict_errors = [
            e for e in entries
            if e.level == "ERROR" or (e.status_code is not None and e.status_code >= 500)
        ]
        error_rate = len(strict_errors) / svc_total * 100 if svc_total else 0.0
        indicators.append({
            "service": svc,
            "indicator_name": "Error Rate",
            "current_value": round(error_rate, 2),
            "severity": ("CRITICAL" if error_rate > 15
                         else "HIGH" if error_rate > 10
                         else "MEDIUM" if error_rate > 5
                         else "NORMAL"),
            "detail": f"{len(strict_errors)}/{svc_total} entries (ERROR/5xx only)",
        })

        # -- Separate Warn/Throttle Rate --
        warns = [e for e in entries if e.level == "WARN"]
        warn_rate = len(warns) / svc_total * 100 if svc_total else 0.0
        indicators.append({
            "service": svc,
            "indicator_name": "Warn/Throttle Rate",
            "current_value": round(warn_rate, 2),
            "severity": ("HIGH" if warn_rate > 20
                         else "MEDIUM" if warn_rate > 10
                         else "NORMAL"),
            "detail": f"{len(warns)}/{svc_total} entries (WARN only)",
        })

        # ---- Service-specific indicators ----

        if svc == "payment_api":
            _payment_api_indicators(entries, svc, indicators)

        elif svc == "charging_controller":
            _charging_controller_indicators(entries, svc, indicators)

        elif svc == "notification_service":
            _notification_service_indicators(entries, svc, indicators)

    return {
        "data_context": store.get_data_context(),
        "service": service or "all_services",
        "time_window": time_window,
        "reference_time": store.reference_time.isoformat(),
        "total_entries_in_window": total,
        "indicators": indicators,
    }


# --------------------------------------------------
#  Payment API specific indicators
# --------------------------------------------------
def _payment_api_indicators(
    entries: List[LogEntry], svc: str, indicators: List[Dict[str, Any]]
) -> None:
    """DB slow queries, external timeouts, connection pool exhaustion."""

    # DB slow queries + missing index note extraction (FIXED)
    db_slow = [e for e in entries if e.event_type == "database_query_slow"]
    missing_index_count = sum(
        1 for e in db_slow
        if "missing_index_suspected" in e.metadata.get("note", "")
    )
    detail = f"database_query_slow events: {len(db_slow)}"
    if missing_index_count > 0:
        detail += f" (missing_index_suspected: {missing_index_count})"
    indicators.append({
        "service": svc,
        "indicator_name": "DB Slow Queries",
        "current_value": float(len(db_slow)),
        "severity": "HIGH" if len(db_slow) > 10 else "MEDIUM" if len(db_slow) > 3 else "NORMAL",
        "detail": detail,
    })

    # External API timeouts
    ext_timeout = [e for e in entries if e.event_type == "external_api_timeout"]
    indicators.append({
        "service": svc,
        "indicator_name": "External API Timeouts",
        "current_value": float(len(ext_timeout)),
        "severity": "HIGH" if len(ext_timeout) > 5 else "MEDIUM" if len(ext_timeout) > 1 else "NORMAL",
        "detail": f"external_api_timeout events: {len(ext_timeout)}",
    })

    # Connection Pool Exhaustion (FIXED: correct search terms)
    _pool_keywords = ("pool exhausted", "timeout waiting for pool", "no available connections")
    conn_pool_hits = [
        e for e in entries
        if any(kw in str(e.metadata.get("stack_trace", "")).lower() for kw in _pool_keywords)
    ]
    pool_sev = ("CRITICAL" if len(conn_pool_hits) > 5
                else "HIGH" if len(conn_pool_hits) > 2
                else "NORMAL")
    indicators.append({
        "service": svc,
        "indicator_name": "DB Connection Pool Exhaustion",
        "current_value": float(len(conn_pool_hits)),
        "severity": pool_sev,
        "detail": f"stack_trace pool exhaustion signals: {len(conn_pool_hits)}",
    })

    # --- DB Catastrophic Outliers (db_query_time_ms > 3000ms) ---
    db_outliers = [
        e for e in entries
        if e.db_query_time_ms is not None and e.db_query_time_ms > 3000
    ]
    indicators.append({
        "service": svc,
        "indicator_name": "DB Outlier Queries (>3s)",
        "current_value": float(len(db_outliers)),
        "severity": "CRITICAL" if len(db_outliers) > 10 else "HIGH" if len(db_outliers) > 3 else "NORMAL",
        "detail": f"Queries exceeding 3000ms: {len(db_outliers)}",
    })


# --------------------------------------------------
#  Charging Controller specific indicators (ENHANCED)
# --------------------------------------------------
def _charging_controller_indicators(
    entries: List[LogEntry], svc: str, indicators: List[Dict[str, Any]]
) -> None:
    """Hardware errors, session metrics, station grouping, duration drift, energy anomalies."""

    # Hardware communication errors
    hw_err = [e for e in entries if e.event_type == "hardware_communication_error"]
    indicators.append({
        "service": svc,
        "indicator_name": "Hardware Errors",
        "current_value": float(len(hw_err)),
        "severity": "CRITICAL" if len(hw_err) > 10 else "HIGH" if len(hw_err) > 5 else "NORMAL",
        "detail": f"hardware_communication_error events: {len(hw_err)}",
    })

    # Session completion rate
    started = sum(1 for e in entries if e.event_type == "charging_session_started")
    completed = sum(1 for e in entries if e.event_type == "charging_session_completed")
    if started > 0:
        completion_rate = completed / started * 100
        indicators.append({
            "service": svc,
            "indicator_name": "Session Completion Rate",
            "current_value": round(completion_rate, 1),
            "severity": "HIGH" if completion_rate < 70 else "MEDIUM" if completion_rate < 85 else "NORMAL",
            "detail": f"Completed: {completed}/{started} sessions",
        })

    # --- ENHANCED: Group errors by station_id ---
    station_errors: Dict[str, int] = defaultdict(int)
    for e in entries:
        if e.level == "ERROR" and e.station_id:
            station_errors[e.station_id] += 1

    if station_errors:
        # Sort by error count descending, take top 5
        top_stations = sorted(station_errors.items(), key=lambda x: x[1], reverse=True)[:5]
        indicators.append({
            "service": svc,
            "indicator_name": "Errors by Station (Top 5)",
            "current_value": float(sum(station_errors.values())),
            "severity": "HIGH" if top_stations[0][1] > 5 else "MEDIUM" if top_stations[0][1] > 2 else "NORMAL",
            "detail": ", ".join(f"{sid}: {cnt}" for sid, cnt in top_stations),
        })

    # --- Recurring Issues ---
    recurring_count = sum(
        1 for e in entries
        if e.metadata.get("note") == "recurring_issue"
    )
    if recurring_count > 0:
        indicators.append({
            "service": svc,
            "indicator_name": "Recurring Issues",
            "current_value": float(recurring_count),
            "severity": "HIGH" if recurring_count > 5 else "MEDIUM" if recurring_count > 1 else "NORMAL",
            "detail": f"Logs flagged as recurring_issue: {recurring_count}",
        })

    # --- FIXED: Session Duration Drift (join started -> completed) ---
    started_sessions = [e for e in entries if e.event_type == "charging_session_started"]
    completed_sessions = [e for e in entries if e.event_type == "charging_session_completed"]

    # Build lookup: (station_id, user_id) -> estimated_duration_min from started events
    estimated_lookup: Dict[tuple, float] = {}
    for e in started_sessions:
        key = (e.station_id, e.user_id)
        est = e.metadata.get("estimated_duration_min")
        if est is not None:
            estimated_lookup[key] = float(est)

    drift_data: List[Dict[str, Any]] = []
    for e in completed_sessions:
        actual = e.metadata.get("duration_min")
        if actual is None:
            continue
        actual_f = float(actual)
        key = (e.station_id, e.user_id)
        estimated_f = estimated_lookup.get(key)
        if estimated_f is not None and estimated_f > 0:
            drift_pct = round(((actual_f - estimated_f) / estimated_f) * 100, 1)
            drift_data.append({
                "station_id": e.station_id,
                "actual_min": actual_f,
                "estimated_min": estimated_f,
                "drift_pct": drift_pct,
            })

    if drift_data:
        avg_drift = round(sum(d["drift_pct"] for d in drift_data) / len(drift_data), 1)
        max_drift = max(drift_data, key=lambda x: abs(x["drift_pct"]))
        indicators.append({
            "service": svc,
            "indicator_name": "Session Duration Drift",
            "current_value": avg_drift,
            "severity": "HIGH" if abs(avg_drift) > 30 else "MEDIUM" if abs(avg_drift) > 15 else "NORMAL",
            "detail": (
                f"Avg drift: {avg_drift}%, Max drift: {max_drift['drift_pct']}% "
                f"(station {max_drift['station_id']}), Samples: {len(drift_data)}"
            ),
        })

    # --- FIXED: Energy Anomalies (completed but < 1.0 kWh → failed micro-sessions) ---
    low_energy = [
        e for e in completed_sessions
        if e.metadata.get("energy_delivered_kwh") is not None
        and float(e.metadata["energy_delivered_kwh"]) < 1.0
    ]
    if low_energy:
        affected_stations = list(set(e.station_id for e in low_energy if e.station_id))[:5]
        indicators.append({
            "service": svc,
            "indicator_name": "Energy Anomalies (<1 kWh delivered)",
            "current_value": float(len(low_energy)),
            "severity": "CRITICAL" if len(low_energy) > 5 else "HIGH" if len(low_energy) > 1 else "MEDIUM",
            "detail": f"Sessions completed with <1 kWh: {len(low_energy)}, stations: {', '.join(affected_stations)}",
        })


# --------------------------------------------------
#  Notification Service specific indicators
# --------------------------------------------------
def _notification_service_indicators(
    entries: List[LogEntry], svc: str, indicators: List[Dict[str, Any]]
) -> None:
    """Queue delays, queue depth/backlog, retry exhaustion, delivery failures."""

    # Queue wait times
    queue_times = tuple(
        e.queue_wait_time_ms
        for e in entries
        if e.queue_wait_time_ms is not None
    )
    if queue_times:
        q_median = median(queue_times)
        q_p90 = percentile(queue_times, 90)
        indicators.append({
            "service": svc,
            "indicator_name": "Queue Wait Time (P50)",
            "current_value": round(q_median, 1),
            "severity": "HIGH" if q_median > 300 else "MEDIUM" if q_median > 150 else "NORMAL",
            "detail": f"Median: {q_median:.1f}ms, P90: {q_p90:.1f}ms",
        })

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
            detail_str += f", Burn Rate: {burn_seconds:.0f}s to clear ({float(rate)}/sec)"

        indicators.append({
            "service": svc,
            "indicator_name": "Queue Depth (Backlog)",
            "current_value": latest_depth,
            "severity": depth_sev,
            "detail": detail_str,
        })

    # Retry exhaustion
    exhausted = [
        e for e in entries
        if e.retry_count > 0 and e.max_retries and e.retry_count >= e.max_retries
    ]
    indicators.append({
        "service": svc,
        "indicator_name": "Retry Exhaustion",
        "current_value": float(len(exhausted)),
        "severity": "HIGH" if len(exhausted) > 10 else "MEDIUM" if len(exhausted) > 3 else "NORMAL",
        "detail": f"Entries at max retries: {len(exhausted)}",
    })

    # Delivery failures
    failed = [e for e in entries if e.event_type == "message_failed"]
    indicators.append({
        "service": svc,
        "indicator_name": "Delivery Failures",
        "current_value": float(len(failed)),
        "severity": "HIGH" if len(failed) > 10 else "MEDIUM" if len(failed) > 3 else "NORMAL",
        "detail": f"message_failed events: {len(failed)}",
    })
