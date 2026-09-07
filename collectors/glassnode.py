"""Optional Glassnode API adapter; no key means explicit unavailable values."""
from datetime import date, datetime, timedelta, timezone
import math

from .base import HTTPCollector, MetricPoint, MetricStatus, unavailable


class GlassnodeCollector(HTTPCollector):
    BASE = "https://api.glassnode.com/v1/metrics"
    ENDPOINTS = {
        "global_mvrv": "market/mvrv",
        "mvrv_zscore": "market/mvrv_z_score",
        "realized_price": "market/price_realized_usd",
        "lth_mvrv": "market/mvrv_more_155",
        "sth_mvrv": "market/mvrv_less_155",
        "sth_realized_price": "market/price_realized_less_155_usd",
        "lth_sopr": "indicators/sopr_more_155",
        "sth_sopr": "indicators/sopr_less_155",
        "asopr": "indicators/sopr_adjusted",
        "lth_supply": "supply/lth_sum",
        "sth_supply": "supply/sth_sum",
        "lth_spent_volume": "transactions/transfers_volume_entity_adjusted_from_lth_sum",
        "sth_spent_volume": "transactions/transfers_volume_entity_adjusted_from_sth_sum",
        "lth_realized_profit": "indicators/realized_profit_lth_account_based",
        "lth_realized_loss": "indicators/realized_loss_lth_account_based",
        "cdd": "indicators/cdd",
        "dormancy": "indicators/average_dormancy",
    }

    def __init__(self, api_key: str | None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.api_key = api_key.strip() if api_key else None

    def _fetch_metric(self, metric: str, start_date: date, end_date: date, *, endpoint: str | None = None) -> list[MetricPoint]:
        if not self.api_key:
            return [unavailable(metric, "Glassnode", MetricStatus.UNAVAILABLE_NO_API_KEY)]
        endpoint = endpoint or self.ENDPOINTS[metric]
        try:
            rows = self._get_json(f"{self.BASE}/{endpoint}", params={"a": "BTC", "api_key": self.api_key, "i": "24h", "s": int(datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc).timestamp()), "u": int(datetime.combine(end_date, datetime.max.time(), tzinfo=timezone.utc).timestamp())})
            if not isinstance(rows, list):
                raise ValueError("Invalid Glassnode response schema")
            fetched = datetime.now(timezone.utc)
            points = []
            for row in rows:
                try:
                    timestamp = datetime.fromtimestamp(row["t"], timezone.utc)
                except (KeyError, TypeError, ValueError, OverflowError, OSError):
                    continue
                if not start_date <= timestamp.date() <= end_date:
                    continue
                value = None
                status = MetricStatus.MISSING
                metadata = {"asset": "BTC", "provider_metric": endpoint}
                if "entity_adjusted" in endpoint or "account_based" in endpoint:
                    metadata["methodology"] = "ENTITY_ADJUSTED"
                if row.get("v") not in (None, ""):
                    try:
                        value = float(row["v"])
                        if not math.isfinite(value) or (metric != "mvrv_zscore" and value < 0):
                            raise ValueError("Invalid numeric observation")
                        if ("mvrv" in metric or "price" in metric) and metric != "mvrv_zscore" and value == 0:
                            raise ValueError("Invalid zero ratio or price")
                        status = MetricStatus.OK
                    except (TypeError, ValueError, OverflowError):
                        value = None
                        status = MetricStatus.ERROR
                        metadata["error"] = "Invalid numeric observation"
                points.append(MetricPoint(metric_name=metric, timestamp=timestamp, value=value,
                    source="Glassnode API v1", fetched_at=fetched, status=status, metadata=metadata))
            return points or [unavailable(metric, "Glassnode", MetricStatus.MISSING)]
        except Exception as exc:
            code = getattr(getattr(exc, "response", None), "status_code", None)
            status = MetricStatus.UNAVAILABLE_PLAN if code in {401, 403} else MetricStatus.UNAVAILABLE if code == 404 else MetricStatus.ERROR
            point = unavailable(metric, "Glassnode", status)
            point.metadata["error"] = f"HTTP {code}" if code else type(exc).__name__
            return [point]

    def fetch_history(self, start_date: date, end_date: date) -> list[MetricPoint]:
        if start_date > end_date:
            raise ValueError("start_date must not be after end_date")
        points = [point for metric in self.ENDPOINTS for point in self._fetch_metric(metric, start_date, end_date)]
        # The current market catalog has STH realized price but no LTH price
        # endpoint. Recover the latter only from same-provider, same-timestamp
        # measured price and LTH MVRV (an arithmetic identity).
        lth_points = [point for point in points if point.metric_name == "lth_mvrv"]
        lth = {point.timestamp: point for point in lth_points if point.status == MetricStatus.OK and point.value is not None}
        derived = []
        if lth:
            prices = self._fetch_metric("btc_price_usd", start_date, end_date, endpoint="market/price_usd_close")
            for price in prices:
                mvrv = lth.get(price.timestamp)
                if mvrv is None or mvrv.value <= 0 or price.status != MetricStatus.OK or price.value is None or price.value <= 0:
                    continue
                value = price.value / mvrv.value
                if math.isfinite(value):
                    derived.append(MetricPoint(metric_name="lth_realized_price", timestamp=price.timestamp,
                        value=value, source="CALCULATED_FROM_GLASSNODE_PRICE_LTH_MVRV",
                        fetched_at=max(price.fetched_at, mvrv.fetched_at), status=MetricStatus.OK,
                        metadata={"asset": "BTC", "formula": "price_usd_close / mvrv_more_155",
                            "input_sources": ["Glassnode API v1"]}))
        if not derived:
            status = MetricStatus.UNAVAILABLE_NO_API_KEY if not self.api_key else MetricStatus.MISSING
            if not lth and lth_points:
                status = lth_points[-1].status
            derived = [unavailable("lth_realized_price", "Glassnode", status)]
        return points + derived

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
