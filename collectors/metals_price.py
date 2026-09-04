"""API-key-free Gold/Silver closes with explicit proxy provenance.

Yahoo symbols are tried in configured order.  A futures or ETF close is never
presented as a spot quote: ``price_type`` is carried to persistence and the UI.
"""
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote

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

    def fetch_history(self, start_date: date, end_date: date) -> list[MetricPoint]:
        period1 = int(datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc).timestamp())
        period2 = int(datetime.combine(end_date + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc).timestamp())
        errors = []
        for symbol, price_type in self.symbols:
            source = f"Yahoo Finance {symbol}"
            try:
                response = self.client.get(
                    f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol, safe='')}",
                    params={"period1": period1, "period2": period2, "interval": "1d", "events": "history"},
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                response.raise_for_status()
                chart = response.json().get("chart", {})
                if chart.get("error") or not chart.get("result"):
                    raise ValueError("Yahoo chart returned no result")
                payload = chart["result"][0]
                timestamps = payload.get("timestamp") or []
                closes = (((payload.get("indicators") or {}).get("quote") or [{}])[0].get("close") or [])
                fetched = datetime.now(timezone.utc)
                result = []
                for epoch, close in zip(timestamps, closes):
                    if close is None:
                        continue
                    timestamp = datetime.fromtimestamp(epoch, timezone.utc)
                    if start_date <= timestamp.date() <= end_date:
                        result.append(MetricPoint(
                            metric_name=f"{self.asset}_price_usd", timestamp=timestamp, value=float(close),
                            source=source, fetched_at=fetched, status=MetricStatus.OK,
                            metadata={"asset": self.asset.upper(), "effective_date": timestamp.date().isoformat(),
                                      "price_type": price_type, "symbol": symbol},
                        ))
                if result:
                    return result
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
