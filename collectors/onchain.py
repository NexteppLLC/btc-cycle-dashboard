"""Keyless, measured on-chain data and transparent arithmetic identities."""
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
import math

from .base import BaseCollector, MetricPoint, MetricStatus, unavailable
from .coinmetrics import CoinMetricsCollector


class OnChainCollector(BaseCollector):
    """Keep published MVRV and derive only timestamp-aligned identities.

    Coin Metrics publishes CapMVRVCur (market cap / realized cap) in its free
    catalog. Realized cap and price can therefore be recovered algebraically
    from that measurement; no LTH/STH cohort value is estimated.
    """
    DERIVATIONS = (
        ("realized_cap_usd", "market_cap_usd", "global_mvrv", "CALCULATED_FROM_MARKET_CAP_MVRV"),
        ("global_mvrv", "market_cap_usd", "realized_cap_usd", "CALCULATED_FROM_MARKET_CAP_REALIZED_CAP"),
        ("realized_price", "realized_cap_usd", "btc_supply", "CALCULATED_FROM_REALIZED_CAP_SUPPLY"),
    )

    def __init__(self, *args, **kwargs):
        self.upstream = CoinMetricsCollector(*args, **kwargs)

    def fetch_history(self, start_date: date, end_date: date) -> list[MetricPoint]:
        points = list(self.upstream.fetch_history(start_date, end_date))
        rows = defaultdict(dict)
        for point in points:
            if point.status == MetricStatus.OK and point.value is not None and math.isfinite(point.value):
                rows[point.timestamp][point.metric_name] = point
        fetched = datetime.now(timezone.utc)
        for timestamp, values in rows.items():
            for name, numerator_name, denominator_name, source in self.DERIVATIONS:
                if name in values:
                    continue
                numerator, denominator = values.get(numerator_name), values.get(denominator_name)
                if numerator is None or denominator is None or numerator.value <= 0 or denominator.value <= 0:
                    continue
                value = numerator.value / denominator.value
                if not math.isfinite(value):
                    continue
                point = MetricPoint(metric_name=name, timestamp=timestamp,
                    value=value, source=source, fetched_at=fetched, status=MetricStatus.OK,
                    metadata={"asset": "BTC", "formula": f"{numerator_name} / {denominator_name}",
                        "input_sources": [numerator.source, denominator.source]})
                points.append(point)
                values[name] = point
        for name, _, _, source in self.DERIVATIONS:
            if not any(point.metric_name == name for point in points):
                point = unavailable(name, source, MetricStatus.MISSING)
                point.metadata = {"asset": "BTC", "error": "No same-timestamp measured inputs"}
                points.append(point)
        measured = {(point.metric_name, point.timestamp) for point in points
                    if point.status == MetricStatus.OK and point.value is not None}
        return [point for point in points if point.value is not None
                or (point.metric_name, point.timestamp) not in measured]

    def fetch_latest(self) -> list[MetricPoint]:
        today = datetime.now(timezone.utc).date()
        points = self.fetch_history(today - timedelta(days=7), today)
        latest = {}
        for point in points:
            current = latest.get(point.metric_name)
            if current is None or (point.value is not None and (
                current.value is None or point.timestamp >= current.timestamp
            )) or (current.value is None and point.timestamp >= current.timestamp):
                latest[point.metric_name] = point
        return list(latest.values())
