"""Coin Metrics Community API v4 collector.

Uses the official community host and /v4/timeseries/asset-metrics endpoint.
"""
from datetime import date, datetime, time, timezone

from .base import HTTPCollector, MetricPoint, MetricStatus, unavailable


class CoinMetricsCollector(HTTPCollector):
    BASE_URL = "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"
    METRICS = "PriceUSD,CapRealUSD,CapMrktCurUSD,AdrActCnt,TxCnt"

    def fetch_history(self, start_date: date, end_date: date) -> list[MetricPoint]:
        try:
            payload = self._get_json(self.BASE_URL, params={"assets": "btc", "metrics": self.METRICS, "frequency": "1d", "start_time": start_date.isoformat(), "end_time": end_date.isoformat(), "page_size": 10000})
            fetched = datetime.now(timezone.utc)
            output: list[MetricPoint] = []
            mapping = {"PriceUSD": "btc_price_usd", "CapRealUSD": "realized_cap_usd", "CapMrktCurUSD": "market_cap_usd", "AdrActCnt": "active_addresses", "TxCnt": "transaction_count"}
            for row in payload.get("data", []):
                timestamp = datetime.fromisoformat(row["time"].replace("Z", "+00:00"))
                for field, name in mapping.items():
                    raw = row.get(field)
                    output.append(MetricPoint(metric_name=name, timestamp=timestamp, value=float(raw) if raw not in (None, "") else None, source="Coin Metrics Community API v4", fetched_at=fetched, status=MetricStatus.OK if raw not in (None, "") else MetricStatus.MISSING))
            return output
        except Exception:
            return [unavailable("coinmetrics", "Coin Metrics Community API v4")]

    def fetch_latest(self) -> list[MetricPoint]:
        today = datetime.now(timezone.utc).date()
        return self.fetch_history(today, today)

