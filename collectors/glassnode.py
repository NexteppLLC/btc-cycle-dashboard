"""Optional Glassnode API adapter; no key means explicit unavailable values."""
from datetime import date, datetime, timedelta, timezone
import math

from .base import HTTPCollector, MetricPoint, MetricStatus, unavailable
from indicators.btc_core import calendar_sma, sell_side_raw


class GlassnodeCollector(HTTPCollector):
    BASE = "https://api.glassnode.com/v1/metrics"
    SOURCE = "Glassnode API v1"
    LTH_PRICE_SOURCE = "CALCULATED_FROM_GLASSNODE_PRICE_LTH_MVRV"
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
    SELL_SIDE_ENDPOINTS = {
        "sell_side_realized_profit_usd": "indicators/realized_profit",
        "sell_side_realized_loss_usd": "indicators/realized_loss",
        "sell_side_realized_cap_usd": "market/marketcap_realized_usd",
    }

    def __init__(self, api_key: str | None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.api_key = api_key.strip() if api_key else None

    def _fetch_metric(self, metric: str, start_date: date, end_date: date, *, endpoint: str | None = None) -> list[MetricPoint]:
        if not self.api_key:
            return [self._unavailable(metric, MetricStatus.UNAVAILABLE_NO_API_KEY)]
        endpoint = endpoint or self.ENDPOINTS[metric]
        try:
            params = {"a": "BTC", "api_key": self.api_key, "i": "24h", "s": int(datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc).timestamp()), "u": int(datetime.combine(end_date, datetime.max.time(), tzinfo=timezone.utc).timestamp())}
            if metric in self.SELL_SIDE_ENDPOINTS:
                params["c"] = "USD"
            rows = self._get_json(f"{self.BASE}/{endpoint}", params=params)
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
                if metric in self.SELL_SIDE_ENDPOINTS:
                    metadata.update({"unit": "USD", "methodology": "GLASSNODE_NETWORK_REALIZED_VALUE",
                                     "provider_timestamp": timestamp.isoformat()})
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
                    source=self.SOURCE, fetched_at=fetched, status=status, metadata=metadata))
            return points or [self._unavailable(metric, MetricStatus.MISSING)]
        except Exception as exc:
            code = getattr(getattr(exc, "response", None), "status_code", None)
            status = MetricStatus.UNAVAILABLE_PLAN if code in {401, 403} else MetricStatus.UNAVAILABLE if code == 404 else MetricStatus.ERROR
            point = self._unavailable(metric, status)
            point.metadata["error"] = f"HTTP {code}" if code else type(exc).__name__
            return [point]

    def _unavailable(self, metric: str, status: MetricStatus) -> MetricPoint:
        source = self.LTH_PRICE_SOURCE if metric == "lth_realized_price" else self.SOURCE
        # Request failures are availability diagnostics, not replacements for
        # an already measured observation on the same UTC day.
        point = unavailable(metric, f"{source} availability", status)
        point.metadata["asset"] = "BTC"
        return point

    def fetch_history(self, start_date: date, end_date: date) -> list[MetricPoint]:
        if start_date > end_date:
            raise ValueError("start_date must not be after end_date")
        points = [point for metric in self.ENDPOINTS for point in self._fetch_metric(metric, start_date, end_date)]
        sell_inputs = [point for metric, endpoint in self.SELL_SIDE_ENDPOINTS.items()
                       for point in self._fetch_metric(metric, start_date - timedelta(days=14), end_date, endpoint=endpoint)]
        points.extend(sell_inputs)
        points.extend(self._sell_side_points(sell_inputs, start_date, end_date))
        # The current market catalog has STH realized price but no LTH price
        # endpoint. Recover the latter only from same-provider, same-timestamp
        # measured price and LTH MVRV (an arithmetic identity).
        lth_points = [point for point in points if point.metric_name == "lth_mvrv"]
        lth = {point.timestamp: point for point in lth_points if point.status == MetricStatus.OK and point.value is not None}
        derived = []
        prices = []
        if lth:
            prices = self._fetch_metric("btc_price_usd", start_date, end_date, endpoint="market/price_usd_close")
            for price in prices:
                mvrv = lth.get(price.timestamp)
                if mvrv is None or mvrv.value <= 0 or price.status != MetricStatus.OK or price.value is None or price.value <= 0:
                    continue
                value = price.value / mvrv.value
                if math.isfinite(value):
                    derived.append(MetricPoint(metric_name="lth_realized_price", timestamp=price.timestamp,
                        value=value, source=self.LTH_PRICE_SOURCE,
                        fetched_at=max(price.fetched_at, mvrv.fetched_at), status=MetricStatus.OK,
                        metadata={"asset": "BTC", "formula": "price_usd_close / mvrv_more_155",
                            "input_sources": [self.SOURCE]}))
        # A failed/missing latest input also makes the identity unavailable at
        # that instant. Keep its exact status and source lineage even when older
        # aligned inputs produced valid history above.
        derived_timestamps = {point.timestamp for point in derived}
        failed_inputs = {}
        for point in lth_points + prices:
            if point.status == MetricStatus.OK or point.timestamp in derived_timestamps:
                continue
            previous = failed_inputs.get(point.timestamp)
            if previous is None or previous.status == MetricStatus.MISSING:
                failed_inputs[point.timestamp] = point
        for point in failed_inputs.values():
            source = (f"{self.LTH_PRICE_SOURCE} availability"
                      if point.source.endswith(" availability") else self.LTH_PRICE_SOURCE)
            derived.append(MetricPoint(metric_name="lth_realized_price", timestamp=point.timestamp,
                value=None, source=source, fetched_at=point.fetched_at,
                status=point.status, metadata={"asset": "BTC",
                    "error": point.metadata.get("error", "Glassnode price/LTH MVRV input unavailable"),
                    "input_sources": [self.SOURCE]}))
        if not derived:
            status = MetricStatus.UNAVAILABLE_NO_API_KEY if not self.api_key else MetricStatus.MISSING
            if not lth and lth_points:
                status = lth_points[-1].status
            derived = [self._unavailable("lth_realized_price", status)]
        return points + derived

    def _sell_side_points(self, inputs, start_date, end_date):
        """Derive only exact-timestamp, same-provider, confirmed UTC daily values."""
        by_metric = {name: {} for name in self.SELL_SIDE_ENDPOINTS}
        request_diagnostics = []
        for point in inputs:
            if point.metric_name not in by_metric:
                continue
            if point.source.endswith(" availability"):
                request_diagnostics.append(point)
            else:
                by_metric[point.metric_name].setdefault(point.timestamp.date(), []).append(point)
        raw = {}
        raw_points = []
        # The UTC day in progress is not a confirmed daily observation.
        confirmed_before = datetime.now(timezone.utc).date()
        observed_days = set().union(*(set(rows) for rows in by_metric.values()))
        for day in sorted(observed_days):
            if day >= confirmed_before:
                continue
            candidates = [by_metric[name].get(day, []) for name in self.SELL_SIDE_ENDPOINTS]
            triplet = [rows[-1] for rows in candidates if len(rows) == 1]
            timestamps = {point.timestamp for point in triplet}
            valid = len(triplet) == 3 and len(timestamps) == 1 and all(
                p.status == MetricStatus.OK and p.value is not None and p.source == self.SOURCE
                and p.metadata.get("asset") == "BTC" and p.metadata.get("unit") == "USD"
                and p.metadata.get("methodology") == "GLASSNODE_NETWORK_REALIZED_VALUE" for p in triplet)
            timestamp = min(timestamps) if timestamps else datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc)
            fetched_at = max((p.fetched_at for rows in candidates for p in rows), default=datetime.now(timezone.utc))
            value = sell_side_raw(*(p.value for p in triplet)) if valid else None
            if value is None:
                status = MetricStatus.ERROR if any(p.status == MetricStatus.ERROR for rows in candidates for p in rows) or (len(triplet) == 3 and len(timestamps) != 1) else MetricStatus.MISSING
                raw_points.append(MetricPoint(metric_name="sell_side_risk_raw", timestamp=timestamp, value=None,
                    source=self.SOURCE, fetched_at=fetched_at, status=status,
                    metadata={"asset": "BTC", "unit": "ratio", "methodology": "(realized_profit_usd + realized_loss_usd) / realized_cap_usd",
                              "formula": "(profit + loss) / realized_cap", "provider_timestamp": timestamp.isoformat(),
                              "error": "Sell-Side inputs missing, invalid, or not aligned"}))
                continue
            raw[day] = value
            raw_points.append(MetricPoint(metric_name="sell_side_risk_raw", timestamp=timestamp, value=value,
                source=self.SOURCE, fetched_at=fetched_at, status=MetricStatus.OK,
                metadata={"asset": "BTC", "unit": "ratio", "methodology": "(realized_profit_usd + realized_loss_usd) / realized_cap_usd",
                          "formula": "(profit + loss) / realized_cap", "provider_timestamp": timestamp.isoformat(),
                          "input_metrics": list(self.SELL_SIDE_ENDPOINTS)}))
        derived = list(raw_points)
        for day in (start_date + timedelta(days=offset) for offset in range((end_date - start_date).days + 1)):
            if day >= confirmed_before:
                continue
            value = calendar_sma(raw, day, 15)
            matching = [p for p in raw_points if p.timestamp.date() == day]
            timestamp = matching[-1].timestamp if matching else datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc)
            fetched_at = max((p.fetched_at for p in raw_points
                              if day - timedelta(days=14) <= p.timestamp.date() <= day), default=datetime.now(timezone.utc))
            if value is not None:
                derived.append(MetricPoint(metric_name="sell_side_risk_15d", timestamp=timestamp, value=value,
                    source=self.SOURCE, fetched_at=fetched_at, status=MetricStatus.OK,
                    metadata={"asset": "BTC", "unit": "ratio", "methodology": "15_calendar_day_simple_moving_average",
                              "formula": "SMA15(sell_side_risk_raw)", "provider_timestamp": timestamp.isoformat()}))
            else:
                derived.append(MetricPoint(metric_name="sell_side_risk_15d", timestamp=timestamp, value=None,
                    source=self.SOURCE, fetched_at=fetched_at, status=MetricStatus.MISSING,
                    metadata={"asset": "BTC", "unit": "ratio", "methodology": "15_calendar_day_simple_moving_average",
                              "formula": "SMA15(sell_side_risk_raw)", "provider_timestamp": timestamp.isoformat(),
                              "error": "連続15暦日の有効なSell-Side raw入力が揃っていません"}))
        if request_diagnostics:
            point = max(request_diagnostics, key=lambda p: p.fetched_at)
            derived.append(MetricPoint(metric_name="sell_side_risk_15d", timestamp=point.timestamp, value=None,
                source=f"{self.SOURCE} Sell-Side Risk availability", fetched_at=point.fetched_at, status=point.status,
                metadata={"asset": "BTC", "unit": "ratio", "methodology": "15_calendar_day_simple_moving_average",
                          "error": point.metadata.get("error", "Sell-Side input unavailable")}))
        elif not any(p.metric_name == "sell_side_risk_15d" for p in derived):
            status = MetricStatus.UNAVAILABLE_NO_API_KEY if not self.api_key else MetricStatus.MISSING
            point = self._unavailable("sell_side_risk_15d", status)
            point.metadata.update({"unit": "ratio", "methodology": "15_calendar_day_simple_moving_average"})
            derived.append(point)
        return derived

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
