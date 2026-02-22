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

from pydantic import BaseModel, Field, field_validator

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

    # -- UTC enforcement at model level ------------------
    @field_validator("timestamp", mode="before")
    @classmethod
    def _ensure_utc(cls, v: Any) -> datetime:
        """Normalise every timestamp to UTC on construction."""
        if isinstance(v, str):
            v = datetime.fromisoformat(v)
        if isinstance(v, datetime):
            if v.tzinfo is None:
                return v.replace(tzinfo=timezone.utc)
            return v.astimezone(timezone.utc)
        return v  # let Pydantic raise if wrong type

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
        """Resolve response time across all 3 services (priority order).

        1. Root response_time_ms        (payment_api)
        2. metadata.response_time_ms    (charging_controller)
        3. metadata.processing_time_ms  (notification_service)
        """
        if self.response_time_ms is not None:
            return self.response_time_ms
        val = self.metadata.get("response_time_ms")
        if val is not None:
            return float(val)
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

    @property
    def is_fast_failure(self) -> bool:
        """Client error (4xx) with rt < 100ms -> likely LB reject.

        5xx errors are NOT fast failures, even if fast -- they are
        server crashes that must remain in latency stats.
        """
        if (self.status_code is not None
                and 400 <= self.status_code < 500):
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
                        # UTC enforcement handled by LogEntry.@field_validator
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
