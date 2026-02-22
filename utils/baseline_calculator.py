"""
baseline_calculator.py -- Math Helpers & Severity Logic
========================================================
Refactored for Phase 2 critical review:
  - SEVERITY_THRESHOLDS corrected to spec (10x / 5x / 2x)
  - No caching on percentile/median (unique float lists → zero hit-rate, memory leak)

Contains:
  - SEVERITY_THRESHOLDS (ratio-based)
  - severity_label()        ratio -> CRITICAL/HIGH/MEDIUM/NORMAL
  - percentile()            linear-interpolation percentile
  - median()                statistics.median wrapper
  - parse_window_to_timedelta()  "1h"/"30m"/"2d" -> timedelta
"""

from __future__ import annotations

import statistics
from datetime import timedelta
from typing import List


# --------------------------------------------------
#  Severity thresholds (multiplier over baseline)
#  CORRECTED to spec: CRITICAL >= 10x, HIGH >= 5x, MEDIUM >= 2x
# --------------------------------------------------
SEVERITY_THRESHOLDS = {
    "CRITICAL": 10.0,  # >= 10x baseline
    "HIGH":     5.0,   # >= 5x baseline
    "MEDIUM":   2.0,   # >= 2x baseline
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


def percentile(data, pct: float) -> float:
    """Return the p-th percentile (0-100 scale) via linear interpolation.

    Accepts list or tuple of floats.
    """
    if not data:
        return 0.0
    sorted_d = sorted(data)
    k = (len(sorted_d) - 1) * (pct / 100.0)
    f = int(k)
    c = f + 1
    if c >= len(sorted_d):
        return sorted_d[-1]
    return sorted_d[f] + (k - f) * (sorted_d[c] - sorted_d[f])


def median(data) -> float:
    """Return the median, or 0.0 for empty data.

    Accepts list or tuple of floats.
    """
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
