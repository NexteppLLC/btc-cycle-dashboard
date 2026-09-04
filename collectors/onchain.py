"""Keyless, measured on-chain data and transparent cap-based derivations."""
from collections import defaultdict
from datetime import date, datetime, timezone

from .base import BaseCollector, MetricPoint, MetricStatus
from .coinmetrics import CoinMetricsCollector


class OnChainCollector(BaseCollector):
    """Collect Coin Metrics Community observations and derive only identities.

    MVRV and realized price are arithmetic identities based on same-timestamp
    measured inputs.  No LTH/STH cohort value is estimated in free mode.
    """
    def __init__(self, *args, **kwargs):
        self.upstream = CoinMetricsCollector(*args, **kwargs)

    def fetch_history(self, start_date: date, end_date: date) -> list[MetricPoint]:
        points = self.upstream.fetch_history(start_date, end_date)
        rows = defaultdict(dict)
        for point in points:
            if point.value is not None:
                rows[point.timestamp][point.metric_name] = point.value
        fetched = datetime.now(timezone.utc)
        for timestamp, values in rows.items():
            pairs = (
                ("global_mvrv", values.get("market_cap_usd"), values.get("realized_cap_usd"), "CALCULATED_FROM_MARKET_CAP_REALIZED_CAP"),
                ("realized_price", values.get("realized_cap_usd"), values.get("btc_supply"), "CALCULATED_FROM_REALIZED_CAP_SUPPLY"),
            )
            for name, numerator, denominator, source in pairs:
                if numerator is not None and denominator not in (None, 0):
                    points.append(MetricPoint(metric_name=name, timestamp=timestamp,
                        value=numerator / denominator, source=source, fetched_at=fetched,
                        status=MetricStatus.OK, metadata={"asset": "BTC"}))
        return points

    def fetch_latest(self) -> list[MetricPoint]:
        today = datetime.now(timezone.utc).date()
        return self.fetch_history(today, today)
