"""
tools/visualization.py — Performance Visualization Tools
=========================================================
Tool 5: generate_latency_chart
    Scatter plot of response_time_ms over time with rolling median trend line.
    Overlays red spike-window bands from detect_slow_requests.

Tool 6: generate_error_heatmap
    Seaborn heatmap of error counts per hour × service over a time window.

Guardrails implemented (see CHECKLIST at bottom).
"""

from __future__ import annotations

# GUARDRAIL 1: Set Agg backend FIRST, before any pyplot import.
import matplotlib
matplotlib.use("Agg")  # non-interactive backend, required for CLI/server use
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, List

from utils.log_parser import LogStore, LogEntry
from utils.baseline_calculator import median as _median
from tools.latency_analysis import detect_slow_requests

# GUARDRAIL 6: seaborn import with fallback
try:
    import seaborn as sns
    _SEABORN_AVAILABLE = True
except ImportError:
    _SEABORN_AVAILABLE = False

# Charts output directory (sibling of this file's package → project root / charts)
_CHARTS_DIR = Path(__file__).resolve().parent.parent / "charts"

SERVICES = ["payment_api", "charging_controller", "notification_service"]
_SERVICE_COLORS = {
    "payment_api":          "#4C72B0",
    "charging_controller":  "#DD8452",
    "notification_service": "#55A868",
}


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _ensure_charts_dir() -> Path:
    """GUARDRAIL 4: Create charts/ with exist_ok=True."""
    _CHARTS_DIR.mkdir(parents=True, exist_ok=True)
    return _CHARTS_DIR


def _utc_stamp() -> str:
    """GUARDRAIL 5: UTC timestamp for filenames — no collisions."""
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _rolling_median(values: List[float], window: int = 30) -> List[float]:
    """
    GUARDRAIL 9: Manual rolling median — no pandas.
    For each position i, computes median over values[max(0,i-window+1):i+1].
    """
    result = []
    for i in range(len(values)):
        start = max(0, i - window + 1)
        chunk = sorted(values[start : i + 1])
        mid = len(chunk) // 2
        if len(chunk) % 2 == 1:
            result.append(float(chunk[mid]))
        else:
            result.append((chunk[mid - 1] + chunk[mid]) / 2.0)
    return result


def _safe_float(val) -> Optional[float]:
    """GUARDRAIL 10: Safe numeric conversion for metadata values."""
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


# ──────────────────────────────────────────────────────────────────────────────
# Tool 5: generate_latency_chart
# ──────────────────────────────────────────────────────────────────────────────

def generate_latency_chart(
    store: LogStore,
    service: Optional[str] = None,
    time_window: str = "24h",
) -> dict:
    """
    Plot response_time_ms vs timestamp as a scatter plot with rolling median
    trend line. Overlays spike windows from detect_slow_requests as red bands.

    Args:
        store:       LogStore singleton.
        service:     One of the 3 service names, or None for all services.
        time_window: How far back to look (e.g. "24h", "6h").

    Returns:
        dict with filepath, entry_count, spike_windows_marked,
        and data_context. On error, returns a dict with an "error" key.
    """
    data_ctx = store.get_data_context()

    # ── 1. Fetch filtered entries ──────────────────────────────────────────
    entries: List[LogEntry] = store.filter(service=service, time_window=time_window)

    # GUARDRAIL 7: Filter to entries that actually have a response time.
    timed_entries = [
        e for e in entries
        if _safe_float(e.effective_response_time_ms) is not None
    ]

    # Insufficient data guard — fire BEFORE touching matplotlib.
    if len(timed_entries) < 10:
        return {
            "error": "insufficient_data",
            "entry_count": len(timed_entries),
            "minimum_required": 10,
            "data_context": data_ctx,
        }

    # ── 2. Collect spike windows from detect_slow_requests ────────────────
    slow_result = detect_slow_requests(store, service=service, time_window=time_window)
    spike_windows = slow_result.get("spike_windows", [])

    # ── 3. Sort timed_entries by timestamp ────────────────────────────────
    timed_entries.sort(key=lambda e: e.timestamp)

    timestamps = [e.timestamp for e in timed_entries]
    rt_values  = [float(e.effective_response_time_ms) for e in timed_entries]

    # ── 4. Log-scale decision (GUARDRAIL 8) ───────────────────────────────
    max_rt    = max(rt_values)
    median_rt = _median(rt_values) or 1.0
    use_log   = (max_rt > 10 * median_rt) and (max_rt > 5000)

    # ── 5. Rolling median ─────────────────────────────────────────────────
    rolling = _rolling_median(rt_values, window=30)

    # ── 6. Plot (wrapped in try/except — GUARDRAIL 3) ─────────────────────
    try:
        _ensure_charts_dir()
        fig, ax = plt.subplots(figsize=(14, 6))

        # Scatter: color by service if service=None, single color otherwise
        if service is None:
            for svc, color in _SERVICE_COLORS.items():
                svc_ts  = [e.timestamp for e in timed_entries if e.service == svc]
                svc_rt  = [float(e.effective_response_time_ms) for e in timed_entries if e.service == svc]
                if svc_ts:
                    ax.scatter(svc_ts, svc_rt, s=8, alpha=0.45, color=color,
                               label=svc, zorder=2)
        else:
            color = _SERVICE_COLORS.get(service, "#4C72B0")
            ax.scatter(timestamps, rt_values, s=8, alpha=0.45, color=color,
                       label=service, zorder=2)

        # Rolling median trend line
        ax.plot(timestamps, rolling, color="#E63946", linewidth=1.6,
                label="Rolling median (30-pt)", zorder=3)

        # Spike window overlays (vertical red bands)
        for sw in spike_windows:
            try:
                sw_start = datetime.fromisoformat(sw["window_start"])
                sw_end   = datetime.fromisoformat(sw["window_end"])
                ax.axvspan(sw_start, sw_end, alpha=0.15, color="red", zorder=1)
            except (KeyError, ValueError, TypeError):
                pass

        # Axes
        if use_log:
            ax.set_yscale("log")
            ax.set_ylabel("Response Time (ms) — log scale")
        else:
            ax.set_ylabel("Response Time (ms)")

        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d %H:%M"))
        fig.autofmt_xdate(rotation=30, ha="right")
        ax.set_xlabel("Timestamp")
        ax.set_title(f"Latency Over Time — {service or 'All Services'} ({time_window})")
        ax.legend(loc="upper right", fontsize=8)
        ax.grid(True, alpha=0.3, linestyle="--")

        # Save
        slug   = service.replace("_", "-") if service else "all"
        fname  = f"latency_{slug}_{time_window}_{_utc_stamp()}.png"
        fpath  = _ensure_charts_dir() / fname
        fig.savefig(fpath, dpi=130, bbox_inches="tight")

        # GUARDRAIL 2: Always close after save.
        plt.close(fig)

        return {
            "chart_type": "latency_timeseries",
            "filepath": str(fpath),
            "entry_count": len(timed_entries),
            "spike_windows_marked": len(spike_windows),
            "log_scale_applied": use_log,
            "data_context": data_ctx,
        }

    except Exception as exc:
        # GUARDRAIL 3: Never let a rendering error bubble as a traceback.
        try:
            plt.close("all")
        except Exception:
            pass
        return {
            "error": "chart_generation_failed",
            "details": str(exc),
            "data_context": data_ctx,
        }


# ──────────────────────────────────────────────────────────────────────────────
# Tool 6: generate_error_heatmap
# ──────────────────────────────────────────────────────────────────────────────

def generate_error_heatmap(
    store: LogStore,
    time_window: str = "48h",
) -> dict:
    """
    Build a 2D error heatmap: rows = hours (newest at top), columns = services.
    Cell value = number of error-level entries in that hour for that service.

    An entry is counted as an error if any of these is true:
      - level == "ERROR"
      - status_code >= 400
      - metadata.final_status == "failed"

    Args:
        store:       LogStore singleton.
        time_window: e.g. "48h", "24h".

    Returns:
        dict with filepath, total_errors, peak_hour, peak_hour_count,
        and data_context. On error, returns a dict with an "error" key.
    """
    data_ctx = store.get_data_context()

    # ── 1. Parse time_window ──────────────────────────────────────────────
    try:
        hours_back = int(time_window.rstrip("h"))
    except (ValueError, AttributeError):
        hours_back = 48

    ref = store.reference_time  # tz-aware datetime

    # ── 2. Fetch all entries in window ────────────────────────────────────
    all_entries: List[LogEntry] = store.filter(time_window=time_window)

    # ── 3. Build hour-bucket grid ─────────────────────────────────────────
    # grid[hour_index][service_index]  hour_index 0 = most recent hour
    grid   = [[0] * 3 for _ in range(hours_back)]
    labels = []  # y-axis: "Feb 20 23:00" per hour (newest first → oldest)

    # Precompute bucket start times for labeling
    for h in range(hours_back):
        bucket_end   = ref - timedelta(hours=h)
        bucket_start = bucket_end - timedelta(hours=1)
        labels.append(bucket_start.strftime("%b %d %H:%M"))

    def _is_error(e: LogEntry) -> bool:
        if e.level == "ERROR":
            return True
        sc = e.status_code
        if sc is not None:
            try:
                if int(sc) >= 400:
                    return True
            except (ValueError, TypeError):
                pass
        # GUARDRAIL 10: safe metadata access
        try:
            fs = e.metadata.get("final_status")
            if fs == "failed":
                return True
        except (AttributeError, TypeError):
            pass
        return False

    svc_index = {svc: i for i, svc in enumerate(SERVICES)}
    total_errors = 0

    for e in all_entries:
        if not _is_error(e):
            continue
        # Which hour bucket? (0 = most recent)
        delta_hours = int((ref - e.timestamp).total_seconds() / 3600)
        if 0 <= delta_hours < hours_back:
            svc_i = svc_index.get(e.service)
            if svc_i is not None:
                grid[delta_hours][svc_i] += 1
                total_errors += 1

    if total_errors == 0:
        return {
            "error": "no_errors_found",
            "time_window": time_window,
            "data_context": data_ctx,
        }

    # ── 4. Find peak hour ─────────────────────────────────────────────────
    peak_hour_idx   = max(range(hours_back), key=lambda h: sum(grid[h]))
    peak_hour_count = sum(grid[peak_hour_idx])
    peak_hour_label = labels[peak_hour_idx]

    # ── 5. Plot ───────────────────────────────────────────────────────────
    try:
        _ensure_charts_dir()

        # Only show hours that have at least one error OR are in the first/last bucket
        # to keep the chart readable for wide time windows.
        # For ≤ 48h just show all rows.
        display_rows = hours_back  # full grid

        import numpy as np_like  # avoid pandas; use list-of-lists directly

        col_labels = ["payment_api", "charging_ctrl", "notification"]

        fig, ax = plt.subplots(figsize=(max(8, len(col_labels) * 2.5),
                                        max(6, display_rows * 0.35)))

        grid_display = grid[:display_rows]
        labels_display = labels[:display_rows]

        result_dict = {
            "chart_type": "error_heatmap",
            "filepath": "",
            "total_errors": total_errors,
            "peak_hour": peak_hour_label,
            "peak_hour_count": peak_hour_count,
            "data_context": data_ctx,
        }
        _seaborn_warning = None

        if _SEABORN_AVAILABLE:
            sns.heatmap(
                grid_display,
                annot=True,
                fmt="d",
                cmap="YlOrRd",
                linewidths=0.5,
                xticklabels=col_labels,
                yticklabels=labels_display,
                ax=ax,
                cbar_kws={"label": "Error Count"},
            )
        else:
            # GUARDRAIL 6: matplotlib fallback
            import math
            flat_max = max(max(row) for row in grid_display) or 1
            img_data = [[v / flat_max for v in row] for row in grid_display]
            ax.imshow(img_data, aspect="auto", cmap="YlOrRd",
                      vmin=0, vmax=1, interpolation="nearest")
            ax.set_xticks(range(len(col_labels)))
            ax.set_xticklabels(col_labels, fontsize=8)
            ax.set_yticks(range(len(labels_display)))
            ax.set_yticklabels(labels_display, fontsize=6)
            # Annotate cells manually
            for ri, row in enumerate(grid_display):
                for ci, val in enumerate(row):
                    ax.text(ci, ri, str(val), ha="center", va="center",
                            fontsize=7, color="black")
            _seaborn_warning = "seaborn_unavailable_used_fallback"

        ax.set_title(f"Error Heatmap — {time_window} Window")
        ax.set_xlabel("Service")
        ax.set_ylabel("Hour (UTC)")

        fname  = f"heatmap_{time_window}_{_utc_stamp()}.png"
        fpath  = _ensure_charts_dir() / fname
        fig.savefig(fpath, dpi=130, bbox_inches="tight")

        # GUARDRAIL 2: Always close after save.
        plt.close(fig)

        result_dict["filepath"] = str(fpath)
        if _seaborn_warning:
            result_dict["warning"] = _seaborn_warning
        return result_dict

    except Exception as exc:
        try:
            plt.close("all")
        except Exception:
            pass
        return {
            "error": "chart_generation_failed",
            "details": str(exc),
            "data_context": data_ctx,
        }


# ──────────────────────────────────────────────────────────────────────────────
# CHECKLIST
# ──────────────────────────────────────────────────────────────────────────────
# [x] matplotlib Agg backend set before any plt import usage
# [x] plt.close(fig) called after every savefig
# [x] charts/ created with exist_ok=True
# [x] insufficient data guard fires before matplotlib is touched
# [x] seaborn import has fallback (matplotlib imshow + manual annotation)
# [x] try/except wraps plot block, returns error dict on failure
# [x] filename includes UTC timestamp (no collisions)
# [x] no pandas import anywhere in this file
# [x] rolling median uses manual list computation (_rolling_median)
# [x] both tools registered in agent.py TOOL_FUNCTIONS and TOOL_SCHEMAS (see agent.py)
# [x] system_prompt.txt visualization section appended
