"""Measured daily Bitcoin observations from Coin Metrics' keyless API."""
from datetime import date, datetime, timedelta, timezone
import logging
import math
from urllib.parse import parse_qs, urlparse

from .base import HTTPCollector, MetricPoint, MetricStatus, unavailable

logger = logging.getLogger(__name__)


class CoinMetricsCollector(HTTPCollector):
    BASE_URL = "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"
    SOURCE = "Coin Metrics Community API v4"
    # CapMVRVCur is a published Community metric. CapRealUSD is currently
    # restricted; including it without isolation makes the entire request 403.
    # Catalog: https://community-api.coinmetrics.io/v4/catalog-v2/asset-metrics
    FIELDS = {
        "PriceUSD": "btc_price_usd",
        "CapMVRVCur": "global_mvrv",
        "CapMrktCurUSD": "market_cap_usd",
        "SplyCur": "btc_supply",
        "AdrActCnt": "active_addresses",
        "TxCnt": "transaction_count",
    }
    METRICS = ",".join(FIELDS)

    def fetch_history(self, start_date: date, end_date: date) -> list[MetricPoint]:
        if start_date > end_date:
            raise ValueError("start_date must not be after end_date")
        params = {
            "assets": "btc", "metrics": self.METRICS, "frequency": "1d",
            "start_time": start_date.isoformat(), "end_time": end_date.isoformat(),
            "page_size": 10000, "ignore_forbidden_errors": "true",
        }
        fetched = datetime.now(timezone.utc)
        output: dict[tuple[datetime, str], MetricPoint] = {}
        seen_tokens: set[str] = set()
        try:
            while True:
                payload = self._get_json(self.BASE_URL, params=params)
                if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
                    raise ValueError("Invalid Coin Metrics response schema")
                for row in payload["data"]:
                    if not isinstance(row, dict) or row.get("asset", "btc") != "btc":
                        continue
                    try:
                        timestamp = datetime.fromisoformat(row["time"].replace("Z", "+00:00"))
                        if timestamp.tzinfo is None:
                            timestamp = timestamp.replace(tzinfo=timezone.utc)
                        timestamp = timestamp.astimezone(timezone.utc)
                    except (KeyError, TypeError, ValueError, AttributeError):
                        logger.warning("Coin Metrics row omitted: invalid observation timestamp")
                        continue
                    if not start_date <= timestamp.date() <= end_date:
                        continue
                    for field, name in self.FIELDS.items():
                        raw = row.get(field)
                        value = None
                        status = MetricStatus.MISSING
                        metadata = {"asset": "BTC", "provider_metric": field}
                        if raw not in (None, ""):
                            try:
                                value = float(raw)
                                if not math.isfinite(value) or value < 0 or (
                                    field in {"PriceUSD", "CapMVRVCur", "CapMrktCurUSD", "SplyCur"}
                                    and value == 0
                                ):
                                    raise ValueError("Invalid numeric observation")
                                status = MetricStatus.OK
                            except (TypeError, ValueError, OverflowError):
                                value = None
                                status = MetricStatus.ERROR
                                metadata["error"] = "Invalid numeric observation"
                        else:
                            # A daily field for the still-open UTC day is not an
                            # observed historical gap. Keep a dated diagnostic
                            # without hiding the last published daily value.
                            if timestamp.date() == fetched.date():
                                status = MetricStatus.PENDING
                                metadata["error"] = "Current UTC day observation not yet published"
                            else:
                                metadata["error"] = "Metric not returned by provider"
                        point = MetricPoint(metric_name=name, timestamp=timestamp,
                            value=value, source=self.SOURCE, fetched_at=fetched,
                            status=status, metadata=metadata)
                        key = (timestamp, name)
                        if key not in output or value is not None or output[key].value is None:
                            output[key] = point
                token = payload.get("next_page_token")
                if not token and payload.get("next_page_url"):
                    # Reuse our original endpoint and parameters, not an
                    # arbitrary URL supplied in a response.
                    token = parse_qs(urlparse(payload["next_page_url"]).query).get("next_page_token", [None])[0]
                    if not token:
                        raise ValueError("Pagination URL has no continuation token")
                if not token:
                    break
                if not isinstance(token, str) or token in seen_tokens:
                    raise ValueError("Repeated or invalid pagination token")
                seen_tokens.add(token)
                params = {**params, "next_page_token": token}
        except Exception as exc:
            code = getattr(getattr(exc, "response", None), "status_code", None)
            status = MetricStatus.UNAVAILABLE_PLAN if code in {401, 403} else MetricStatus.ERROR
            logger.warning("Coin Metrics collection incomplete (%s)", type(exc).__name__)
            diagnostics = [unavailable(name, self.SOURCE, status) for name in self.FIELDS.values()]
            for point in diagnostics:
                point.metadata["error"] = f"HTTP {code}" if code else type(exc).__name__
            return list(output.values()) + diagnostics
        if not output:
            return [unavailable(name, self.SOURCE, MetricStatus.MISSING) for name in self.FIELDS.values()]
        order = {name: index for index, name in enumerate(self.FIELDS.values())}
        return sorted(output.values(), key=lambda point: (point.timestamp, order[point.metric_name]))

    def fetch_latest(self) -> list[MetricPoint]:
        # Daily network metrics are published after the UTC day has closed.
        today = datetime.now(timezone.utc).date()
        points = self.fetch_history(today - timedelta(days=7), today)
        latest: dict[str, MetricPoint] = {}
        for point in points:
            current = latest.get(point.metric_name)
            if current is None or (point.value is not None and (
                current.value is None or point.timestamp >= current.timestamp
            )) or (current.value is None and point.timestamp >= current.timestamp):
                latest[point.metric_name] = point
        return list(latest.values())
