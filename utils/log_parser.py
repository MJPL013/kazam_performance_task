"""
log_parser.py -- Pydantic Models & Log Loading
===============================================
Refactored for Phase 2 critical review:
  - UTC enforcement on all timestamps
  - Sorted entries by timestamp for O(log n) bisect filtering
  - Service index for O(1) service lookup
  - bisect-based time-window slicing

Contains:
  - LogEntry            (universal model, extra="allow")
  - 6 Result Models     (SlowRequest, EndpointLatencyProfile, ...)
  - LogStore            (file loader + bisect-optimised filter helpers)
"""

from __future__ import annotations

import bisect
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from utils.baseline_calculator import parse_window_to_timedelta


# ======================================================
#  Core Log Entry
# ======================================================

class LogEntry(BaseModel):
    """Universal log entry that covers all 3 services."""

    # -- Required fields (present in every record) ------
    timestamp: datetime
    service: Literal[
        "payment_api",
        "charging_controller",
        "notification_service",
    ]
    level: Literal["INFO", "WARN", "ERROR"]
    event_type: str
    metadata: Dict[str, Any] = Field(default_factory=dict)

    # -- Optional root-level fields (payment_api only) --
    endpoint: Optional[str] = None
    method: Optional[str] = None
    status_code: Optional[int] = None
    response_time_ms: Optional[float] = None

    class Config:
        extra = "allow"

    # -- Helpers: response time resolution ---------------
    @property
    def effective_response_time_ms(self) -> Optional[float]:
        """Root response_time_ms (payment) or metadata (notification)."""
        if self.response_time_ms is not None:
            return self.response_time_ms
        val = self.metadata.get("processing_time_ms")
        return float(val) if val is not None else None

    # -- Helpers: latency breakdown ----------------------
    @property
    def db_query_time_ms(self) -> Optional[float]:
        val = self.metadata.get("db_query_time_ms")
        return float(val) if val is not None else None

    @property
    def external_api_time_ms(self) -> Optional[float]:
        val = self.metadata.get("external_api_time_ms")
        return float(val) if val is not None else None

    @property
    def app_logic_time_ms(self) -> Optional[float]:
        val = self.metadata.get("app_logic_time_ms")
        return float(val) if val is not None else None

    @property
    def queue_wait_time_ms(self) -> Optional[float]:
        val = self.metadata.get("queue_wait_time_ms")
        return float(val) if val is not None else None

    @property
    def unaccounted_latency_ms(self) -> Optional[float]:
        """Total - (DB + External + App).  None if breakdown unavailable."""
        total = self.effective_response_time_ms
        db = self.db_query_time_ms
        ext = self.external_api_time_ms
        app = self.app_logic_time_ms
        if total is not None and all(v is not None for v in (db, ext, app)):
            return max(0.0, total - db - ext - app)
        return None

    # -- Helpers: error classification -------------------
    @property
    def is_fast_failure(self) -> bool:
        """status >= 400 AND response_time < 100ms -> likely LB reject."""
        if self.status_code is not None and self.status_code >= 400:
            rt = self.effective_response_time_ms
            if rt is not None and rt < 100:
                return True
        return False

    @property
    def is_client_error(self) -> bool:
        return self.status_code is not None and 400 <= self.status_code < 500

    @property
    def is_server_error(self) -> bool:
        return self.status_code is not None and self.status_code >= 500

    @property
    def error_message(self) -> Optional[str]:
        return self.metadata.get("error")

    # -- Helpers: retry/stress indicator -----------------
    @property
    def retry_count(self) -> int:
        return int(self.metadata.get("retry_count", 0))

    @property
    def max_retries(self) -> Optional[int]:
        val = self.metadata.get("max_retries")
        return int(val) if val is not None else None

    # -- Helpers: identifiers ----------------------------
    @property
    def station_id(self) -> Optional[str]:
        return self.metadata.get("station_id")

    @property
    def connector_id(self) -> Optional[str]:
        return self.metadata.get("connector_id")

    @property
    def user_id(self) -> Optional[str]:
        return self.metadata.get("user_id")

    # -- Helpers: polymorphic grouping -------------------
    @property
    def group_key(self) -> str:
        """endpoint (payment_api) -> event_type (fallback)."""
        return self.endpoint or self.event_type


# ======================================================
#  Analysis Result Models
# ======================================================

class SlowRequest(BaseModel):
    timestamp: datetime
    service: str
    endpoint_or_event: str
    response_time_ms: float
    threshold_ms: float
    db_query_time_ms: Optional[float] = None
    external_api_time_ms: Optional[float] = None
    app_logic_time_ms: Optional[float] = None
    unaccounted_ms: Optional[float] = None
    user_id: Optional[str] = None


class EndpointLatencyProfile(BaseModel):
    group_key: str
    request_count: int
    median_ms: float
    p90_ms: float
    max_ms: float
    slow_count: int
    baseline_median_ms: Optional[float] = None
    severity: str = "NORMAL"


class LatencyBreakdown(BaseModel):
    group_key: str
    total_median_ms: float
    db_median_ms: Optional[float] = None
    external_median_ms: Optional[float] = None
    app_logic_median_ms: Optional[float] = None
    unaccounted_median_ms: Optional[float] = None
    primary_bottleneck: str = "unknown"
    bottleneck_pct: float = 0.0


class ErrorBucket(BaseModel):
    group_key: str
    total_errors: int
    client_errors: int = 0
    server_errors: int = 0
    error_types: Dict[str, int] = Field(default_factory=dict)
    retry_total: int = 0
    failure_rate_pct: float = 0.0
    affected_users: int = 0


class ResourceHealthIndicator(BaseModel):
    service: str
    indicator_name: str
    current_value: float
    baseline_value: Optional[float] = None
    severity: str = "NORMAL"
    detail: str = ""


class WarnStressSignal(BaseModel):
    service: str
    event_type: str
    count: int
    avg_retry_count: float = 0.0
    max_retry_count: int = 0
    sample_errors: List[str] = Field(default_factory=list)


# ======================================================
#  LogStore -- File Loading + Bisect-Optimised Filtering
# ======================================================

class LogStore:
    """
    Loads and stores all log entries.  Provides filtering helpers
    consumed by the tool modules.

    Architecture (post-refactor):
      - entries sorted by timestamp for O(log n) bisect slicing
      - _by_service index for O(1) service lookup
      - _timestamps parallel list for bisect key lookups

    Parameters
    ----------
    log_dir : str | Path
        Directory containing *.log JSON-line files.
    """

    def __init__(self, log_dir: str | Path) -> None:
        self.log_dir = Path(log_dir)
        self.entries: List[LogEntry] = []
        self.parse_errors: List[Dict[str, Any]] = []
        self._load_all_logs()

        # --- O(log n) optimisation: sort + index ---
        self.entries.sort(key=lambda e: e.timestamp)

        # Parallel timestamp list for bisect lookups
        self._timestamps: List[datetime] = [e.timestamp for e in self.entries]

        # Service index: each sub-list is also sorted (parent is sorted)
        self._by_service: Dict[str, List[LogEntry]] = defaultdict(list)
        for e in self.entries:
            self._by_service[e.service].append(e)

        # Pre-computed per-service timestamp lists for O(log n) bisect
        self._by_service_timestamps: Dict[str, List[datetime]] = {
            svc: [e.timestamp for e in entries]
            for svc, entries in self._by_service.items()
        }

        # Deterministic reference time: latest entry's timestamp
        if self.entries:
            self.reference_time: datetime = self.entries[-1].timestamp  # already sorted
        else:
            self.reference_time = datetime.now(timezone.utc)

    def _load_all_logs(self) -> None:
        """Parse every .log file into validated LogEntry objects."""
        for log_file in sorted(self.log_dir.glob("*.log")):
            with open(log_file, "r", encoding="utf-8") as fh:
                for line_no, raw_line in enumerate(fh, start=1):
                    raw_line = raw_line.strip()
                    if not raw_line:
                        continue
                    try:
                        data = json.loads(raw_line)
                        entry = LogEntry(**data)

                        # --- UTC enforcement ---
                        # If timestamp is naive, assume UTC; otherwise convert.
                        if entry.timestamp.tzinfo is None:
                            entry.timestamp = entry.timestamp.replace(tzinfo=timezone.utc)
                        else:
                            entry.timestamp = entry.timestamp.astimezone(timezone.utc)

                        self.entries.append(entry)
                    except Exception as exc:
                        self.parse_errors.append({
                            "file": log_file.name,
                            "line": line_no,
                            "error": str(exc),
                        })

    # -- Time-window helpers ----------------------------

    def get_start_time(self, window: str) -> datetime:
        """Convert window string to a start datetime relative to reference_time."""
        return self.reference_time - parse_window_to_timedelta(window)

    # -- Bisect helpers (O(log n) time slicing) ---------

    def _bisect_range(
        self,
        entries: List[LogEntry],
        timestamps: List[datetime],
        start: datetime,
        end: Optional[datetime] = None,
    ) -> List[LogEntry]:
        """Slice a sorted entry list by [start, end) using bisect."""
        lo = bisect.bisect_left(timestamps, start)
        if end is not None:
            hi = bisect.bisect_left(timestamps, end)
        else:
            hi = len(entries)
        return entries[lo:hi]

    # -- Filtering helpers (refactored with bisect) -----

    def filter(
        self,
        service: Optional[str] = None,
        time_window: Optional[str] = None,
        level: Optional[str] = None,
        event_type: Optional[str] = None,
        endpoint: Optional[str] = None,
    ) -> List[LogEntry]:
        """Chain multiple filters.  Uses bisect for time, index for service."""

        # Step 1: Pick the right source list + matching timestamps via service index
        if service and service in self._by_service:
            result = self._by_service[service]
            ts_list = self._by_service_timestamps[service]
        elif service:
            result = []  # service not present at all
            ts_list = []
        else:
            result = self.entries
            ts_list = self._timestamps

        # Step 2: Bisect for time window (O(log n)) using pre-computed ts_list
        if time_window and result:
            start = self.get_start_time(time_window)
            result = self._bisect_range(result, ts_list, start)

        # Step 3: Linear filters (already narrowed by service + time)
        if level:
            result = [e for e in result if e.level == level.upper()]
        if event_type:
            result = [e for e in result if e.event_type == event_type]
        if endpoint:
            result = [e for e in result if e.endpoint == endpoint]

        return result

    def filter_range(
        self,
        start: datetime,
        end: datetime,
        service: Optional[str] = None,
        endpoint: Optional[str] = None,
    ) -> List[LogEntry]:
        """Filter entries to a specific [start, end) time range using bisect."""

        # Step 1: Pick source + matching timestamps via service index
        if service and service in self._by_service:
            source = self._by_service[service]
            ts_list = self._by_service_timestamps[service]
        elif service:
            source = []
            ts_list = []
        else:
            source = self.entries
            ts_list = self._timestamps

        # Step 2: Bisect for time range (O(log n)) using pre-computed ts_list
        if source:
            result = self._bisect_range(source, ts_list, start, end)
        else:
            result = []

        # Step 3: Optional endpoint filter
        if endpoint:
            result = [e for e in result if e.endpoint == endpoint]

        return result

    def get_data_context(self) -> dict:
        """Return a dict describing data freshness for tool consumers."""
        staleness_hours = (
            (datetime.now(timezone.utc) - self.reference_time).total_seconds() / 3600
        )
        return {
            "log_data_ends_at": self.reference_time.isoformat(),
            "hours_since_last_log": round(staleness_hours, 2),
            "is_historical": staleness_hours > 2.0,
        }

    @staticmethod
    def exclude_fast_failures(entries: List[LogEntry]) -> List[LogEntry]:
        """Remove fast failures (status>=400, rt<100ms) from latency calcs."""
        return [e for e in entries if not e.is_fast_failure]
