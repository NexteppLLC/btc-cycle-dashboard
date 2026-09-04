"""Optional Glassnode API adapter; no key means explicit unavailable values."""
from datetime import date, datetime, timezone

from .base import HTTPCollector, MetricPoint, MetricStatus, unavailable


class GlassnodeCollector(HTTPCollector):
    BASE = "https://api.glassnode.com/v1/metrics"
    ENDPOINTS = {
        "global_mvrv": "market/mvrv",
        "mvrv_zscore": "market/mvrv_z_score",
        "realized_price": "market/price_realized_usd",
        "lth_mvrv": "indicators/mvrv_more_155",
        "sth_mvrv": "indicators/mvrv_less_155",
        "lth_realized_price": "indicators/realized_price_more_155",
        "sth_realized_price": "indicators/realized_price_less_155",
        "lth_sopr": "indicators/sopr_more_155",
        "sth_sopr": "indicators/sopr_less_155",
        "asopr": "indicators/sopr_adjusted",
        "lth_supply": "supply/lth_sum",
        "sth_supply": "supply/sth_sum",
        "cdd": "indicators/cdd",
    }

    def __init__(self, api_key: str | None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.api_key = api_key

    def _fetch_metric(self, metric: str, start_date: date, end_date: date) -> list[MetricPoint]:
        if not self.api_key:
            return [unavailable(metric, "Glassnode", MetricStatus.UNAVAILABLE_NO_API_KEY)]
        try:
            rows = self._get_json(f"{self.BASE}/{self.ENDPOINTS[metric]}", params={"a": "BTC", "api_key": self.api_key, "i": "24h", "s": int(datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc).timestamp()), "u": int(datetime.combine(end_date, datetime.max.time(), tzinfo=timezone.utc).timestamp())})
            fetched = datetime.now(timezone.utc)
            return [MetricPoint(metric_name=metric, timestamp=datetime.fromtimestamp(row["t"], timezone.utc), value=float(row["v"]) if row.get("v") is not None else None, source="Glassnode API v1", fetched_at=fetched, status=MetricStatus.OK if row.get("v") is not None else MetricStatus.MISSING) for row in rows]
        except Exception as exc:
            status = MetricStatus.UNAVAILABLE if getattr(getattr(exc, "response", None), "status_code", None) in {401, 403, 404} else MetricStatus.ERROR
            return [unavailable(metric, "Glassnode", status)]

    def fetch_history(self, start_date: date, end_date: date) -> list[MetricPoint]:
        return [point for metric in self.ENDPOINTS for point in self._fetch_metric(metric, start_date, end_date)]

    def fetch_latest(self) -> list[MetricPoint]:
        today = datetime.now(timezone.utc).date()
        return self.fetch_history(today, today)
