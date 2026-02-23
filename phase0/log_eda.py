#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
==========================================================================
 Performance Log EDA — Comprehensive Exploratory Data Analysis
==========================================================================
 Author : Phase-0 Pre-Agent Analysis
 Purpose: Deep-dive into JSON-Lines log files to understand schema,
          distributions, edge cases, and missing fields BEFORE building
          the Performance Monitoring AI Agent.

 Usage :  python log_eda.py
==========================================================================
"""

from __future__ import annotations

import json
import os
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# ========================================================================
# GLOBAL CONFIGURATION
# ========================================================================

VERBOSE: bool = True

SOURCE_LOGS_DIR: str = (
    r"E:\Downloads\Resume 2025\Kazam\performance"
    r"\Assignment_PerformanceAgent\performance_logs\performance_logs"
)

TARGET_DIR: str = r"E:\Downloads\Resume 2025\Kazam\phase0"

LOG_FILES: List[str] = [
    "payment_api.log",
    "charging_controller.log",
    "notification_service.log",
]

REPORT_FILENAME: str = "EDA_Comprehensive_Report.md"

# Fast-failure threshold: if response_time_ms is below this AND status is
# 4xx/5xx, we flag it as a "fast failure".
FAST_FAILURE_THRESHOLD_MS: int = 100


# ========================================================================
# UTILITY — Pretty Console Printing
# ========================================================================

_DIVIDER_HEAVY = "=" * 80
_DIVIDER_LIGHT = "-" * 80
_DIVIDER_DOT   = "·" * 80


def _header(title: str, level: int = 1) -> str:
    """Return a formatted header string for console + markdown."""
    if level == 1:
        return f"\n{_DIVIDER_HEAVY}\n  {title}\n{_DIVIDER_HEAVY}"
    elif level == 2:
        return f"\n{_DIVIDER_LIGHT}\n  {title}\n{_DIVIDER_LIGHT}"
    else:
        return f"\n  ── {title} ──"


def _kv(key: str, value: Any, indent: int = 4) -> str:
    """Format a key-value pair for console output."""
    pad = " " * indent
    return f"{pad}• {key:<40s} : {value}"


def _table(headers: List[str], rows: List[List[Any]], indent: int = 6) -> str:
    """Build a simple ASCII table string."""
    if not rows:
        return " " * indent + "(no data)"

    # Calculate column widths
    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(str(cell)))

    pad = " " * indent
    sep = pad + "+-" + "-+-".join("-" * w for w in col_widths) + "-+"
    hdr = pad + "| " + " | ".join(
        str(h).ljust(w) for h, w in zip(headers, col_widths)
    ) + " |"

    lines = [sep, hdr, sep]
    for row in rows:
        line = pad + "| " + " | ".join(
            str(c).ljust(w) for c, w in zip(row, col_widths)
        ) + " |"
        lines.append(line)
    lines.append(sep)
    return "\n".join(lines)


def _md_table(headers: List[str], rows: List[List[Any]]) -> str:
    """Build a GitHub-Flavoured Markdown table."""
    if not rows:
        return "_No data._\n"
    lines: List[str] = []
    lines.append("| " + " | ".join(str(h) for h in headers) + " |")
    lines.append("| " + " | ".join("---" for _ in headers) + " |")
    for row in rows:
        lines.append("| " + " | ".join(str(c) for c in row) + " |")
    return "\n".join(lines) + "\n"


def vprint(*args: Any, **kwargs: Any) -> None:
    """Verbose printer — only outputs when VERBOSE is True."""
    if VERBOSE:
        print(*args, **kwargs)


# ========================================================================
# STEP 1 — LOG PARSING
# ========================================================================

def parse_log_file(filepath: str) -> Tuple[List[Dict[str, Any]], int, int]:
    """
    Parse a JSON-Lines log file.

    Returns
    -------
    records : list[dict]
        Successfully parsed log entries.
    total_lines : int
        Total number of non-empty lines attempted.
    malformed_count : int
        Number of lines that could not be decoded as JSON.
    """
    records: List[Dict[str, Any]] = []
    malformed_count: int = 0
    total_lines: int = 0

    vprint(f"    📂 Parsing: {os.path.basename(filepath)}")

    with open(filepath, "r", encoding="utf-8") as fh:
        for line_no, raw_line in enumerate(fh, start=1):
            stripped = raw_line.strip()
            if not stripped:
                continue
            total_lines += 1
            try:
                record = json.loads(stripped)
                records.append(record)
            except json.JSONDecodeError as exc:
                malformed_count += 1
                if VERBOSE:
                    vprint(
                        f"      ⚠  Malformed JSON on line {line_no}: "
                        f"{exc} — skipping."
                    )

    vprint(
        f"       ✓ Parsed {len(records):,} records  |  "
        f"skipped {malformed_count} malformed  |  "
        f"total lines {total_lines:,}"
    )
    return records, total_lines, malformed_count


def load_all_logs(
    log_dir: str,
    filenames: List[str],
) -> Dict[str, Tuple[List[Dict[str, Any]], int, int]]:
    """
    Load every specified log file from *log_dir*.

    Returns a dict keyed by filename → (records, total_lines, malformed).
    """
    vprint(_header("STEP 1 — Loading & Parsing Log Files", level=1))
    results: Dict[str, Tuple[List[Dict[str, Any]], int, int]] = {}
    for fname in filenames:
        fp = os.path.join(log_dir, fname)
        if not os.path.isfile(fp):
            vprint(f"    ❌ File not found: {fp}")
            continue
        results[fname] = parse_log_file(fp)
    return results


# ========================================================================
# STEP 2 — GENERAL / CROSS-FILE EDA
# ========================================================================

def general_eda(
    data: Dict[str, Tuple[List[Dict[str, Any]], int, int]],
) -> Dict[str, Any]:
    """
    Compute cross-file statistics.

    Returns a report dict with totals, time window, and universal fields.
    """
    vprint(_header("STEP 2 — General EDA (Cross-File)", level=1))

    total_records = 0
    total_lines = 0
    total_malformed = 0
    all_timestamps: List[datetime] = []
    all_keys_per_record: List[Set[str]] = []

    per_file_summary: List[List[Any]] = []

    for fname, (records, lines, malformed) in data.items():
        total_records += len(records)
        total_lines += lines
        total_malformed += malformed
        per_file_summary.append([fname, lines, len(records), malformed])

        for rec in records:
            all_keys_per_record.append(set(rec.keys()))
            ts_str = rec.get("timestamp")
            if ts_str:
                try:
                    dt = datetime.fromisoformat(
                        ts_str.replace("Z", "+00:00")
                    )
                    all_timestamps.append(dt)
                except ValueError:
                    pass

    # Universal fields — present in every single record
    if all_keys_per_record:
        universal_fields = set.intersection(*all_keys_per_record)
    else:
        universal_fields = set()

    earliest = min(all_timestamps) if all_timestamps else None
    latest = max(all_timestamps) if all_timestamps else None
    duration = (latest - earliest) if (earliest and latest) else None

    # Console output
    vprint(_kv("Total non-empty lines across all files", f"{total_lines:,}"))
    vprint(_kv("Total parsed records", f"{total_records:,}"))
    vprint(_kv("Total malformed / skipped", f"{total_malformed:,}"))
    vprint("")
    vprint("    Per-file breakdown:")
    vprint(_table(["File", "Lines", "Parsed", "Malformed"], per_file_summary))
    vprint("")
    vprint(_kv("Earliest timestamp", str(earliest)))
    vprint(_kv("Latest timestamp", str(latest)))
    vprint(_kv("Time span", str(duration)))
    vprint(_kv("Universal fields", ", ".join(sorted(universal_fields))))

    return {
        "total_records": total_records,
        "total_lines": total_lines,
        "total_malformed": total_malformed,
        "per_file_summary": per_file_summary,
        "earliest": earliest,
        "latest": latest,
        "duration": duration,
        "universal_fields": sorted(universal_fields),
    }


# ========================================================================
# STEP 3 — SERVICE-SPECIFIC EDA
# ========================================================================

def _describe_numeric(values: List[float]) -> Dict[str, float]:
    """Return min / max / mean / median / p95 / p99 for a numeric list."""
    if not values:
        return {}
    s = sorted(values)
    n = len(s)
    return {
        "count": n,
        "min": s[0],
        "max": s[-1],
        "mean": round(statistics.mean(s), 2),
        "median": round(statistics.median(s), 2),
        "p95": round(s[int(n * 0.95)], 2) if n > 1 else s[0],
        "p99": round(s[int(n * 0.99)], 2) if n > 1 else s[0],
        "stdev": round(statistics.stdev(s), 2) if n > 1 else 0.0,
    }


def _infer_type(value: Any) -> str:
    """Return a human-readable type name for a value."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "dict"
    return type(value).__name__


def service_eda(
    fname: str,
    records: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Perform per-service deep exploration.

    Returns a report dict with levels, event types, schema, metadata keys,
    and (for payment_api) response-time statistics.
    """
    service_name = fname.replace(".log", "")
    vprint(_header(f"Service EDA — {service_name}", level=2))

    report: Dict[str, Any] = {"service": service_name, "record_count": len(records)}

    # ── 3a. Level distribution ──
    level_counter: Counter = Counter()
    for rec in records:
        level_counter[rec.get("level", "<MISSING>")] += 1
    report["levels"] = dict(level_counter.most_common())

    vprint("    Level Distribution:")
    rows = [[lvl, cnt, f"{cnt / len(records) * 100:.1f}%"]
            for lvl, cnt in level_counter.most_common()]
    vprint(_table(["Level", "Count", "Pct"], rows))

    # ── 3b. Event-type distribution ──
    event_counter: Counter = Counter()
    for rec in records:
        event_counter[rec.get("event_type", "<MISSING>")] += 1
    report["event_types"] = dict(event_counter.most_common())

    vprint("\n    Event Type Distribution:")
    rows = [[et, cnt, f"{cnt / len(records) * 100:.1f}%"]
            for et, cnt in event_counter.most_common()]
    vprint(_table(["Event Type", "Count", "Pct"], rows))

    # ── 3c. Root-level schema ──
    root_keys: Counter = Counter()
    for rec in records:
        for k in rec.keys():
            root_keys[k] += 1
    report["root_keys"] = {
        k: {"count": c, "pct": f"{c / len(records) * 100:.1f}%"}
        for k, c in root_keys.most_common()
    }

    vprint("\n    Root-Level Schema:")
    rows = [[k, c, f"{c / len(records) * 100:.1f}%"]
            for k, c in root_keys.most_common()]
    vprint(_table(["Key", "Present In", "Pct"], rows))

    # ── 3d. Metadata deep-dive ──
    meta_key_types: Dict[str, Counter] = defaultdict(Counter)
    meta_key_counts: Counter = Counter()
    meta_sample_values: Dict[str, List[Any]] = defaultdict(list)
    records_with_meta = 0

    for rec in records:
        meta = rec.get("metadata")
        if not isinstance(meta, dict):
            continue
        records_with_meta += 1
        for k, v in meta.items():
            meta_key_counts[k] += 1
            meta_key_types[k][_infer_type(v)] += 1
            if len(meta_sample_values[k]) < 5:
                meta_sample_values[k].append(v)

    report["metadata_keys"] = {}
    vprint(f"\n    Metadata Deep-Dive  ({records_with_meta} records have metadata):")
    meta_rows = []
    for k, cnt in meta_key_counts.most_common():
        types_str = ", ".join(
            f"{t}({c})" for t, c in meta_key_types[k].most_common()
        )
        pct = f"{cnt / records_with_meta * 100:.1f}%" if records_with_meta else "N/A"
        meta_rows.append([k, cnt, pct, types_str])
        report["metadata_keys"][k] = {
            "count": cnt,
            "pct": pct,
            "types": dict(meta_key_types[k]),
            "sample_values": meta_sample_values[k][:3],
        }
    vprint(_table(["Meta Key", "Count", "Pct", "Types"], meta_rows))

    # ── 3e. Response-time stats (payment_api only) ──
    if "payment" in service_name.lower():
        response_times = [
            rec["response_time_ms"]
            for rec in records
            if "response_time_ms" in rec
            and isinstance(rec["response_time_ms"], (int, float))
        ]
        stats = _describe_numeric(response_times)
        report["response_time_stats"] = stats
        vprint("\n    Response Time Stats (ms):")
        if stats:
            for k, v in stats.items():
                vprint(_kv(k, v))
        else:
            vprint("      (no response_time_ms data found)")

    # ── 3f. Status-code distribution (if present) ──
    status_counter: Counter = Counter()
    has_status = False
    for rec in records:
        sc = rec.get("status_code")
        if sc is not None:
            has_status = True
            status_counter[sc] += 1
    if has_status:
        report["status_codes"] = dict(status_counter.most_common())
        vprint("\n    Status Code Distribution:")
        rows = [[sc, cnt, f"{cnt / len(records) * 100:.1f}%"]
                for sc, cnt in status_counter.most_common()]
        vprint(_table(["Status", "Count", "Pct"], rows))

    # ── 3g. Unique endpoints (if present) ──
    endpoint_counter: Counter = Counter()
    for rec in records:
        ep = rec.get("endpoint")
        if ep:
            endpoint_counter[ep] += 1
    if endpoint_counter:
        report["endpoints"] = dict(endpoint_counter.most_common())
        vprint("\n    Endpoint Distribution:")
        rows = [[ep, cnt] for ep, cnt in endpoint_counter.most_common()]
        vprint(_table(["Endpoint", "Count"], rows))

    return report


# ========================================================================
# STEP 4 — NUANCE & EDGE-CASE DETECTION
# ========================================================================

def detect_edge_cases(
    data: Dict[str, Tuple[List[Dict[str, Any]], int, int]],
) -> Dict[str, Any]:
    """
    Scan for anomalies, fast failures, missing fields, and inconsistencies.
    """
    vprint(_header("STEP 4 — Nuance & Edge-Case Detection", level=1))
    report: Dict[str, Any] = {}

    # ── 4a. Fast failures — high error code + very low response time ──
    fast_failures: List[Dict[str, Any]] = []
    for fname, (records, _, _) in data.items():
        for rec in records:
            sc = rec.get("status_code")
            rt = rec.get("response_time_ms")
            if (
                sc is not None
                and isinstance(sc, int)
                and sc >= 400
                and rt is not None
                and isinstance(rt, (int, float))
                and rt < FAST_FAILURE_THRESHOLD_MS
            ):
                fast_failures.append({
                    "file": fname,
                    "timestamp": rec.get("timestamp"),
                    "endpoint": rec.get("endpoint"),
                    "status_code": sc,
                    "response_time_ms": rt,
                    "event_type": rec.get("event_type"),
                })

    report["fast_failures"] = fast_failures
    vprint(f"\n    Fast Failures (status ≥ 400 AND response_time < {FAST_FAILURE_THRESHOLD_MS}ms):")
    vprint(f"      Found: {len(fast_failures)} occurrences")
    if fast_failures:
        rows = [
            [ff["file"], ff["timestamp"], ff["endpoint"],
             ff["status_code"], ff["response_time_ms"]]
            for ff in fast_failures[:15]  # cap display
        ]
        vprint(_table(
            ["File", "Timestamp", "Endpoint", "Status", "RT(ms)"], rows
        ))
        if len(fast_failures) > 15:
            vprint(f"      … and {len(fast_failures) - 15} more.")

    # ── 4b. ERROR-level logs without 'error' key in metadata ──
    errors_no_desc: List[Dict[str, Any]] = []
    for fname, (records, _, _) in data.items():
        for rec in records:
            if rec.get("level") == "ERROR":
                meta = rec.get("metadata", {})
                if not isinstance(meta, dict) or "error" not in meta:
                    errors_no_desc.append({
                        "file": fname,
                        "timestamp": rec.get("timestamp"),
                        "event_type": rec.get("event_type"),
                        "metadata_keys": list(meta.keys()) if isinstance(meta, dict) else [],
                    })

    report["errors_without_description"] = errors_no_desc
    vprint(f"\n    ERROR-level logs missing 'error' key in metadata:")
    vprint(f"      Found: {len(errors_no_desc)} occurrences")
    if errors_no_desc:
        rows = [
            [e["file"], e["timestamp"], e["event_type"],
             ", ".join(e["metadata_keys"][:5])]
            for e in errors_no_desc[:10]
        ]
        vprint(_table(["File", "Timestamp", "Event", "Meta Keys Present"], rows))

    # ── 4c. Field-location inconsistencies (user_id in root vs metadata) ──
    vprint("\n    Field Location Consistency Check:")
    field_checks = ["user_id", "station_id", "error"]
    inconsistencies: Dict[str, Dict[str, int]] = {}

    for field in field_checks:
        in_root = 0
        in_meta = 0
        in_both = 0
        in_neither = 0
        total_checked = 0

        for fname, (records, _, _) in data.items():
            for rec in records:
                total_checked += 1
                root_has = field in rec
                meta = rec.get("metadata", {})
                meta_has = isinstance(meta, dict) and field in meta

                if root_has and meta_has:
                    in_both += 1
                elif root_has:
                    in_root += 1
                elif meta_has:
                    in_meta += 1
                else:
                    in_neither += 1

        inconsistencies[field] = {
            "in_root_only": in_root,
            "in_metadata_only": in_meta,
            "in_both": in_both,
            "in_neither": in_neither,
            "total": total_checked,
        }
        vprint(
            f"      '{field}': root_only={in_root}  meta_only={in_meta}  "
            f"both={in_both}  neither={in_neither}  (of {total_checked})"
        )

    report["field_inconsistencies"] = inconsistencies

    # ── 4d. WARN-level logs — what are they warning about? ──
    warn_events: Counter = Counter()
    warn_count = 0
    for fname, (records, _, _) in data.items():
        for rec in records:
            if rec.get("level") == "WARN":
                warn_count += 1
                warn_events[rec.get("event_type", "<unknown>")] += 1

    report["warn_breakdown"] = dict(warn_events.most_common())
    vprint(f"\n    WARN-level breakdown ({warn_count} total):")
    rows = [[et, c] for et, c in warn_events.most_common()]
    vprint(_table(["Event Type", "Count"], rows))

    # ── 4e. Timestamp gaps — detect suspiciously long gaps ──
    vprint("\n    Timestamp Gap Analysis (per file):")
    gap_report: Dict[str, Any] = {}
    for fname, (records, _, _) in data.items():
        timestamps: List[datetime] = []
        for rec in records:
            ts_str = rec.get("timestamp")
            if ts_str:
                try:
                    timestamps.append(
                        datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    )
                except ValueError:
                    pass
        timestamps.sort()
        if len(timestamps) < 2:
            continue
        gaps = [
            (timestamps[i + 1] - timestamps[i]).total_seconds()
            for i in range(len(timestamps) - 1)
        ]
        max_gap = max(gaps)
        avg_gap = statistics.mean(gaps)
        median_gap = statistics.median(gaps)
        max_gap_idx = gaps.index(max_gap)
        gap_report[fname] = {
            "max_gap_seconds": round(max_gap, 1),
            "avg_gap_seconds": round(avg_gap, 1),
            "median_gap_seconds": round(median_gap, 1),
            "max_gap_between": (
                str(timestamps[max_gap_idx]),
                str(timestamps[max_gap_idx + 1]),
            ),
        }
        vprint(
            f"      {fname}: max_gap={max_gap:.0f}s  avg={avg_gap:.0f}s  "
            f"median={median_gap:.0f}s"
        )

    report["timestamp_gaps"] = gap_report
    return report


# ========================================================================
# STEP 5 — FUTURE-PROOFING ANALYSIS
# ========================================================================

def future_proofing_analysis(
    data: Dict[str, Tuple[List[Dict[str, Any]], int, int]],
) -> Dict[str, Any]:
    """
    Predict which fields are missing but highly likely to appear in a
    production environment and explain *why* they matter.
    """
    vprint(_header("STEP 5 — Future-Proofing (Predictive Schema)", level=1))

    # Gather all present keys (root + metadata)
    present_root: Set[str] = set()
    present_meta: Set[str] = set()
    for fname, (records, _, _) in data.items():
        for rec in records:
            present_root.update(rec.keys())
            meta = rec.get("metadata", {})
            if isinstance(meta, dict):
                present_meta.update(meta.keys())

    all_present = present_root | present_meta

    # Define fields we'd expect in a production observability stack
    expected_fields: Dict[str, Dict[str, str]] = {
        "trace_id": {
            "rationale": "Distributed tracing is essential for correlating "
                         "requests across microservices (OpenTelemetry / Jaeger).",
            "impact": "Without it, root-cause analysis across service "
                      "boundaries is manual guesswork.",
        },
        "span_id": {
            "rationale": "Companion to trace_id; identifies individual spans "
                         "within a distributed trace.",
            "impact": "Needed for latency waterfall visualisation.",
        },
        "request_id": {
            "rationale": "Unique ID per request for deduplication and "
                         "correlating retry attempts.",
            "impact": "Helps track a single user action end-to-end.",
        },
        "correlation_id": {
            "rationale": "Links asynchronous events (e.g., a payment triggers "
                         "a notification) across services.",
            "impact": "Critical for debugging message-queue-based flows.",
        },
        "ip_address": {
            "rationale": "Client or server IP for geo-based analysis, "
                         "abuse detection, and CDN routing diagnostics.",
            "impact": "Enables regional performance analysis.",
        },
        "region": {
            "rationale": "Cloud region / availability zone for multi-region "
                         "deployments.",
            "impact": "Allows region-specific latency dashboards.",
        },
        "container_id": {
            "rationale": "K8s pod name or Docker container ID; essential for "
                         "isolating issues to a specific replica.",
            "impact": "Without it, noisy-neighbour issues are invisible.",
        },
        "host": {
            "rationale": "Server hostname for bare-metal or VM-based deployments.",
            "impact": "Pinpoints which host is misbehaving.",
        },
        "environment": {
            "rationale": "prod / staging / dev tag; prevents dev logs leaking "
                         "into prod dashboards.",
            "impact": "Operational hygiene.",
        },
        "version": {
            "rationale": "Application version or git SHA; correlates "
                         "performance changes with deployments.",
            "impact": "Enables deployment-aware regression detection.",
        },
        "memory_usage_mb": {
            "rationale": "Process-level memory usage for leak detection.",
            "impact": "Proactive OOM prevention.",
        },
        "cpu_usage_pct": {
            "rationale": "Process-level CPU usage for thread-starvation "
                         "detection.",
            "impact": "Explains latency spikes caused by compute saturation.",
        },
        "thread_count": {
            "rationale": "Active threads for concurrency monitoring.",
            "impact": "Detects thread pool exhaustion.",
        },
        "db_connection_pool_active": {
            "rationale": "Active DB connections for pool-exhaustion detection.",
            "impact": "Explains sudden query latency increases.",
        },
        "cache_hit_ratio": {
            "rationale": "Cache effectiveness metric, crucial for performance.",
            "impact": "Detects cache invalidation storms.",
        },
    }

    missing_fields: Dict[str, Dict[str, str]] = {}
    present_predicted: List[str] = []

    for field, info in expected_fields.items():
        if field in all_present:
            present_predicted.append(field)
        else:
            missing_fields[field] = info

    vprint(f"    Fields already present that match production patterns:")
    vprint(f"      {', '.join(present_predicted) if present_predicted else '(none)'}")
    vprint(f"\n    Missing but highly expected in production ({len(missing_fields)}):")
    rows = [[f, info["rationale"][:70]] for f, info in missing_fields.items()]
    vprint(_table(["Missing Field", "Rationale"], rows))

    return {
        "present_predicted": present_predicted,
        "missing_fields": missing_fields,
    }


# ========================================================================
# STEP 6 — MARKDOWN REPORT GENERATION
# ========================================================================

def generate_markdown_report(
    general: Dict[str, Any],
    service_reports: Dict[str, Dict[str, Any]],
    edge_cases: Dict[str, Any],
    future: Dict[str, Any],
    output_path: str,
) -> None:
    """
    Write a comprehensive Markdown report combining all EDA findings.
    """
    vprint(_header("STEP 6 — Generating Markdown Report", level=1))

    lines: List[str] = []

    def w(s: str = "") -> None:
        lines.append(s)

    w("# 📊 EDA Comprehensive Report — Performance Logs")
    w()
    w(f"_Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}_")
    w()

    # ── 1. General Overview ──
    w("## 1. General Overview")
    w()
    w(f"- **Total parsed records**: {general['total_records']:,}")
    w(f"- **Total lines read**: {general['total_lines']:,}")
    w(f"- **Malformed / skipped**: {general['total_malformed']:,}")
    w(f"- **Earliest timestamp**: `{general['earliest']}`")
    w(f"- **Latest timestamp**: `{general['latest']}`")
    w(f"- **Time span**: `{general['duration']}`")
    w(f"- **Universal fields**: `{', '.join(general['universal_fields'])}`")
    w()
    w("### Per-File Breakdown")
    w()
    w(_md_table(
        ["File", "Lines", "Parsed", "Malformed"],
        general["per_file_summary"],
    ))
    w()

    # ── 2. Service-Specific EDA ──
    w("## 2. Service-Specific EDA")
    w()
    for fname, sr in service_reports.items():
        svc = sr["service"]
        w(f"### 2.{list(service_reports.keys()).index(fname) + 1}. `{svc}` ({sr['record_count']:,} records)")
        w()

        # Levels
        w("#### Level Distribution")
        w()
        total_r = sr["record_count"]
        level_rows = [
            [lvl, cnt, f"{cnt / total_r * 100:.1f}%"]
            for lvl, cnt in sr["levels"].items()
        ]
        w(_md_table(["Level", "Count", "Pct"], level_rows))
        w()

        # Event types
        w("#### Event Types")
        w()
        et_rows = [
            [et, cnt, f"{cnt / total_r * 100:.1f}%"]
            for et, cnt in sr["event_types"].items()
        ]
        w(_md_table(["Event Type", "Count", "Pct"], et_rows))
        w()

        # Root schema
        w("#### Root-Level Schema")
        w()
        rk_rows = [[k, v["count"], v["pct"]] for k, v in sr["root_keys"].items()]
        w(_md_table(["Key", "Present In", "Pct"], rk_rows))
        w()

        # Metadata keys
        w("#### Metadata Keys")
        w()
        mk_rows = [
            [k, v["count"], v["pct"],
             ", ".join(f"{t}({c})" for t, c in v["types"].items()),
             str(v["sample_values"][:2])]
            for k, v in sr["metadata_keys"].items()
        ]
        w(_md_table(
            ["Key", "Count", "Pct", "Types", "Sample Values"], mk_rows
        ))
        w()

        # Response time stats
        if "response_time_stats" in sr and sr["response_time_stats"]:
            w("#### Response Time Stats (ms)")
            w()
            rt = sr["response_time_stats"]
            rt_rows = [[k, v] for k, v in rt.items()]
            w(_md_table(["Metric", "Value"], rt_rows))
            w()

        # Status codes
        if "status_codes" in sr:
            w("#### Status Code Distribution")
            w()
            sc_rows = [[sc, cnt] for sc, cnt in sr["status_codes"].items()]
            w(_md_table(["Status", "Count"], sc_rows))
            w()

        # Endpoints
        if "endpoints" in sr:
            w("#### Endpoint Distribution")
            w()
            ep_rows = [[ep, cnt] for ep, cnt in sr["endpoints"].items()]
            w(_md_table(["Endpoint", "Count"], ep_rows))
            w()

        w("---")
        w()

    # ── 3. Edge Cases ──
    w("## 3. Nuance & Edge-Case Detection")
    w()

    # Fast failures
    ff = edge_cases.get("fast_failures", [])
    w(f"### 3.1 Fast Failures ({len(ff)} found)")
    w()
    w(f"> Requests with HTTP status ≥ 400 **and** response_time < {FAST_FAILURE_THRESHOLD_MS}ms.")
    w(f"> These indicate the server rejected the request before doing meaningful work.")
    w()
    if ff:
        ff_rows = [
            [f["file"], f["timestamp"], f["endpoint"],
             f["status_code"], f["response_time_ms"]]
            for f in ff[:20]
        ]
        w(_md_table(["File", "Timestamp", "Endpoint", "Status", "RT(ms)"], ff_rows))
        if len(ff) > 20:
            w(f"_…and {len(ff) - 20} more._")
    else:
        w("_None found._")
    w()

    # Errors without description
    ewd = edge_cases.get("errors_without_description", [])
    w(f"### 3.2 ERROR Logs Missing Error Description ({len(ewd)} found)")
    w()
    if ewd:
        ewd_rows = [
            [e["file"], e["timestamp"], e["event_type"],
             ", ".join(e["metadata_keys"][:5])]
            for e in ewd[:15]
        ]
        w(_md_table(["File", "Timestamp", "Event", "Meta Keys Present"], ewd_rows))
    else:
        w("_All ERROR-level logs have an 'error' key in metadata._")
    w()

    # Inconsistencies
    w("### 3.3 Field Location Inconsistencies")
    w()
    fi = edge_cases.get("field_inconsistencies", {})
    fi_rows = [
        [field, d["in_root_only"], d["in_metadata_only"],
         d["in_both"], d["in_neither"], d["total"]]
        for field, d in fi.items()
    ]
    w(_md_table(
        ["Field", "Root Only", "Meta Only", "Both", "Neither", "Total"],
        fi_rows,
    ))
    w()

    # WARN breakdown
    wb = edge_cases.get("warn_breakdown", {})
    w("### 3.4 WARN-Level Breakdown")
    w()
    wb_rows = [[et, c] for et, c in wb.items()]
    w(_md_table(["Event Type", "Count"], wb_rows))
    w()

    # Timestamp gaps
    tg = edge_cases.get("timestamp_gaps", {})
    w("### 3.5 Timestamp Gap Analysis")
    w()
    tg_rows = [
        [fname, d["max_gap_seconds"], d["avg_gap_seconds"],
         d["median_gap_seconds"]]
        for fname, d in tg.items()
    ]
    w(_md_table(["File", "Max Gap (s)", "Avg Gap (s)", "Median Gap (s)"], tg_rows))
    w()

    # ── 4. Future-Proofing ──
    w("## 4. Future-Proofing — Predictive Schema Analysis")
    w()
    pp = future.get("present_predicted", [])
    w(f"**Fields already present that match production patterns:** "
      f"`{', '.join(pp) if pp else '(none)'}`")
    w()
    mf = future.get("missing_fields", {})
    w(f"### Missing Fields Expected in Production ({len(mf)} identified)")
    w()
    mf_rows = [
        [field, info["rationale"], info["impact"]]
        for field, info in mf.items()
    ]
    w(_md_table(["Field", "Rationale", "Impact if Missing"], mf_rows))
    w()

    # ── Write to disk ──
    content = "\n".join(lines)
    with open(output_path, "w", encoding="utf-8") as fh:
        fh.write(content)

    vprint(f"    ✅ Report saved to: {output_path}")
    vprint(f"       Size: {len(content):,} characters, {len(lines):,} lines")


# ========================================================================
# MAIN ENTRYPOINT
# ========================================================================

def main() -> None:
    """Orchestrate the full EDA pipeline."""
    print(_header("PERFORMANCE LOG EDA — COMPREHENSIVE ANALYSIS", level=1))
    print(f"  Source : {SOURCE_LOGS_DIR}")
    print(f"  Target : {TARGET_DIR}")
    print(f"  Verbose: {VERBOSE}")
    print()

    # Ensure target directory exists
    os.makedirs(TARGET_DIR, exist_ok=True)

    # STEP 1 — Parse
    data = load_all_logs(SOURCE_LOGS_DIR, LOG_FILES)
    if not data:
        print("  ❌ No log files loaded. Aborting.")
        sys.exit(1)

    # STEP 2 — General EDA
    general_report = general_eda(data)

    # STEP 3 — Service-level EDA
    service_reports: Dict[str, Dict[str, Any]] = {}
    for fname, (records, _, _) in data.items():
        service_reports[fname] = service_eda(fname, records)

    # STEP 4 — Edge cases
    edge_case_report = detect_edge_cases(data)

    # STEP 5 — Future-proofing
    future_report = future_proofing_analysis(data)

    # STEP 6 — Markdown report
    report_path = os.path.join(TARGET_DIR, REPORT_FILENAME)
    generate_markdown_report(
        general_report,
        service_reports,
        edge_case_report,
        future_report,
        report_path,
    )

    print(_header("ALL DONE ✓", level=1))
    print(f"  Report: {report_path}")
    print()


if __name__ == "__main__":
    main()
