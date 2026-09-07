"""API-key-free Gold/Silver closes with explicit proxy provenance.

Yahoo symbols are tried in configured order.  A futures or ETF close is never
presented as a spot quote: ``price_type`` is carried to persistence and the UI.
"""
from datetime import date, datetime, timedelta, timezone
from math import isfinite
from time import sleep
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

from collectors.base import HTTPCollector, MetricPoint, MetricStatus, unavailable
from config.settings import get_settings

DEFAULT_SYMBOLS = {
    "gold": (("XAUUSD=X", "SPOT"), ("GC=F", "FUTURES_PROXY"), ("GLD", "ETF_PROXY")),
    "silver": (("XAGUSD=X", "SPOT"), ("SI=F", "FUTURES_PROXY"), ("SLV", "ETF_PROXY")),
}


class MetalsPriceCollector(HTTPCollector):
    def __init__(self, asset: str, symbols=None, **kwargs):
        asset = asset.lower()
        if asset not in DEFAULT_SYMBOLS:
            raise ValueError("asset must be gold or silver")
        super().__init__(**kwargs)
        self.asset = asset
        configured = get_settings().gold_price_priority if asset == "gold" else get_settings().silver_price_priority
        types = dict(DEFAULT_SYMBOLS[asset])
        self.symbols = tuple(symbols or ((symbol.strip(), types[symbol.strip()]) for symbol in configured.split(",") if symbol.strip() in types))

    def _chart(self, url: str, params: dict) -> dict:
        """Retry transient Yahoo failures while retaining its required headers."""
        for attempt in range(max(1, self.retries)):
            try:
                response = self.client.get(url, params=params, headers={"User-Agent": "Mozilla/5.0"})
                response.raise_for_status()
                return response.json()
            except (httpx.RequestError, httpx.HTTPStatusError, ValueError) as exc:
                retryable = not isinstance(exc, httpx.HTTPStatusError) or exc.response.status_code in {429, 500, 502, 503, 504}
                if not retryable or attempt + 1 >= max(1, self.retries):
                    raise
                sleep(0.25 * (2 ** attempt))
        raise RuntimeError("unreachable")

    def fetch_history(self, start_date: date, end_date: date) -> list[MetricPoint]:
        period1 = int(datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc).timestamp())
        period2 = int(datetime.combine(end_date + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc).timestamp())
        errors = []
        for symbol, price_type in self.symbols:
            source = f"Yahoo Finance {symbol}"
            source_url = f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol, safe='')}"
            try:
                chart = self._chart(source_url, {"period1": period1, "period2": period2,
                    "interval": "1d", "events": "history"}).get("chart", {})
                if chart.get("error") or not chart.get("result"):
                    raise ValueError("Yahoo chart returned no result")
                payload = chart["result"][0]
                meta = payload.get("meta") or {}
                if meta.get("currency", "USD") != "USD" or meta.get("symbol", symbol) != symbol:
                    raise ValueError("Yahoo returned a different symbol or currency")
                try:
                    exchange_tz = ZoneInfo(meta.get("exchangeTimezoneName") or "UTC")
                except (ZoneInfoNotFoundError, ValueError, TypeError):
                    exchange_tz = timezone.utc
                timestamps = payload.get("timestamp") or []
                closes = (((payload.get("indicators") or {}).get("quote") or [{}])[0].get("close") or [])
                fetched = datetime.now(timezone.utc)
                completed_before = fetched.astimezone(exchange_tz).date()
                # An overnight futures session can still be open after its
                # start date has passed. Honor Yahoo's session bounds as well.
                regular = (meta.get("currentTradingPeriod") or {}).get("regular") or {}
                try:
                    session_start = datetime.fromtimestamp(regular["start"], timezone.utc)
                    session_end = datetime.fromtimestamp(regular["end"], timezone.utc)
                    if session_start <= fetched < session_end:
                        completed_before = min(completed_before, session_start.astimezone(exchange_tz).date())
                except (KeyError, TypeError, ValueError, OverflowError, OSError):
                    pass
                result = {}
                for epoch, close in zip(timestamps, closes):
                    try:
                        value = float(close)
                        if isinstance(close, bool) or not isfinite(value) or value <= 0:
                            continue
                        timestamp = datetime.fromtimestamp(epoch, timezone.utc)
                    except (TypeError, ValueError, OverflowError, OSError):
                        continue
                    effective_date = timestamp.astimezone(exchange_tz).date()
                    # Yahoo's last daily row can be an intraday price. Use only
                    # prior exchange dates; a same-day close is not yet verified.
                    if start_date <= effective_date <= end_date and effective_date < completed_before:
                        result[effective_date] = MetricPoint(
                            metric_name=f"{self.asset}_price_usd", timestamp=timestamp, value=value,
                            source=source, fetched_at=fetched, status=MetricStatus.OK,
                            metadata={"asset": self.asset.upper(), "effective_date": effective_date.isoformat(),
                                      "price_type": price_type, "symbol": symbol, "currency": "USD",
                                      "unit": "USD/share" if price_type == "ETF_PROXY" else "USD/troy oz",
                                      "source_url": source_url, "candle_status": "CLOSED",
                                      "exchange_timezone": str(exchange_tz)},
                        )
                if result:
                    return [result[day] for day in sorted(result)]
                raise ValueError("Yahoo chart contained no usable closes")
            except Exception as exc:
                errors.append(f"{symbol}: {type(exc).__name__}")
        point = unavailable(f"{self.asset}_price_usd", "Yahoo Finance fallback chain", MetricStatus.UNAVAILABLE)
        point.metadata = {"asset": self.asset.upper(), "price_type": None, "effective_date": None,
                          "error": "; ".join(errors)}
        return [point]

    def fetch_latest(self) -> list[MetricPoint]:
        today = datetime.now(timezone.utc).date()
        return self.fetch_history(today - timedelta(days=10), today)[-1:]
