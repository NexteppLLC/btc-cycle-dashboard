"""Common resilient collector contract."""
from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from datetime import date, datetime, timezone
from enum import StrEnum
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict

logger = logging.getLogger(__name__)


class MetricStatus(StrEnum):
    OK = "OK"
    STALE = "STALE"
    MISSING = "MISSING"
    ERROR = "ERROR"
    PENDING = "PENDING"
    UNAVAILABLE = "UNAVAILABLE"
    UNAVAILABLE_PLAN = "UNAVAILABLE_PLAN"
    UNAVAILABLE_NO_API_KEY = "UNAVAILABLE_NO_API_KEY"


class MetricPoint(BaseModel):
    """A measured value with explicit provenance and availability."""

    metric_name: str
    timestamp: datetime
    value: float | None
    source: str
    fetched_at: datetime
    status: MetricStatus
    metadata: dict[str, Any] = {}
    model_config = ConfigDict(use_enum_values=False)


class BaseCollector(ABC):
    """Interface shared by all collectors."""

    @abstractmethod
    def fetch_latest(self) -> list[MetricPoint]: ...

    @abstractmethod
    def fetch_history(self, start_date: date, end_date: date) -> list[MetricPoint]: ...


class HTTPCollector(BaseCollector):
    """HTTP collector with finite exponential retries and safe diagnostics."""

    def __init__(self, timeout: float = 20, retries: int = 3, client: httpx.Client | None = None):
        self.retries = retries
        self.client = client or httpx.Client(timeout=timeout, follow_redirects=True)

    def _get_json(self, url: str, *, params: dict[str, Any] | None = None) -> Any:
        for attempt in range(self.retries):
            try:
                response = self.client.get(url, params=params)
                response.raise_for_status()
                return response.json()
            except (httpx.RequestError, httpx.HTTPStatusError, ValueError) as exc:
                retryable = not isinstance(exc, httpx.HTTPStatusError) or exc.response.status_code in {429, 500, 502, 503, 504}
                logger.warning("API request failed (%s), attempt %d/%d", type(exc).__name__, attempt + 1, self.retries)
                if not retryable or attempt == self.retries - 1:
                    raise
                time.sleep(0.25 * (2**attempt))
        raise RuntimeError("unreachable")


def unavailable(metric: str, source: str, status: MetricStatus = MetricStatus.ERROR) -> MetricPoint:
    now = datetime.now(timezone.utc)
    return MetricPoint(metric_name=metric, timestamp=now, value=None, source=source, fetched_at=now, status=status,
                       metadata={"asset": "BTC"} if source in {"Glassnode", "Coin Metrics Community API v4"} else {})
