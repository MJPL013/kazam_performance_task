"""
baseline_calculator.py -- Math Helpers & Severity Logic
========================================================
Extracted from Phase 1 PerformanceAnalyzer.

Contains:
  - SEVERITY_THRESHOLDS (ratio-based)
  - _severity_label()        ratio -> CRITICAL/HIGH/MEDIUM/NORMAL
  - _percentile()            linear-interpolation percentile
  - _median()                statistics.median wrapper
  - parse_window_to_timedelta()  "1h"/"30m"/"2d" -> timedelta
"""

from __future__ import annotations

import statistics
from datetime import timedelta
from typing import List


# --------------------------------------------------
#  Severity thresholds (multiplier over baseline)
# --------------------------------------------------
SEVERITY_THRESHOLDS = {
    "CRITICAL": 3.0,   # >= 3x baseline
    "HIGH":     2.0,   # >= 2x baseline
    "MEDIUM":   1.5,   # >= 1.5x baseline
}


def severity_label(current: float, baseline: float) -> str:
    """Map current value to a severity label vs baseline."""
    if baseline <= 0:
        return "NORMAL"
    ratio = current / baseline
    for label, threshold in SEVERITY_THRESHOLDS.items():
        if ratio >= threshold:
            return label
    return "NORMAL"


def percentile(data: List[float], pct: float) -> float:
    """Return the p-th percentile (0-100 scale) via linear interpolation."""
    if not data:
        return 0.0
    sorted_d = sorted(data)
    k = (len(sorted_d) - 1) * (pct / 100.0)
    f = int(k)
    c = f + 1
    if c >= len(sorted_d):
        return sorted_d[-1]
    return sorted_d[f] + (k - f) * (sorted_d[c] - sorted_d[f])


def median(data: List[float]) -> float:
    """Return the median, or 0.0 for an empty list."""
    return statistics.median(data) if data else 0.0


def parse_window_to_timedelta(window: str) -> timedelta:
    """Convert human-readable window ('1h', '30m', '2d') to timedelta."""
    window = window.strip().lower()
    if window.endswith("h"):
        return timedelta(hours=float(window[:-1]))
    elif window.endswith("m"):
        return timedelta(minutes=float(window[:-1]))
    elif window.endswith("d"):
        return timedelta(days=float(window[:-1]))
    else:
        try:
            return timedelta(hours=float(window))
        except ValueError:
            return timedelta(hours=24)
