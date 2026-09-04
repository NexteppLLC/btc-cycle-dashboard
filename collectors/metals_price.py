"""Daily metal prices: Stooq spot first, then clearly-labelled Yahoo proxies."""
import csv
import io
from datetime import date, datetime, timedelta, timezone

from collectors.base import HTTPCollector, MetricPoint, MetricStatus, unavailable

SYMBOLS = {"gold": "xauusd", "silver": "xagusd"}
YAHOO = {"gold": (("GC=F", "FUTURES_PROXY"), ("GLD", "ETF_PROXY")),
         "silver": (("SI=F", "FUTURES_PROXY"), ("SLV", "ETF_PROXY"))}


class MetalsPriceCollector(HTTPCollector):
    def __init__(self, asset: str, **kwargs):
        asset = asset.lower()
        if asset not in SYMBOLS:
            raise ValueError("asset must be gold or silver")
        super().__init__(**kwargs); self.asset = asset

    def fetch_history(self, start_date: date, end_date: date) -> list[MetricPoint]:
        source = f"Stooq {SYMBOLS[self.asset].upper()} USD spot proxy"
        try:
            response = self.client.get("https://stooq.com/q/d/l/", params={"s": SYMBOLS[self.asset],
                "d1": start_date.strftime("%Y%m%d"), "d2": end_date.strftime("%Y%m%d")})
            response.raise_for_status(); fetched = datetime.now(timezone.utc); result = []
            for row in csv.DictReader(io.StringIO(response.text)):
                try:
                    timestamp = datetime.fromisoformat(row["Date"]).replace(tzinfo=timezone.utc)
                    close = float(row["Close"])
                except (KeyError, TypeError, ValueError):
                    continue
                result.append(MetricPoint(metric_name=f"{self.asset}_price_usd", timestamp=timestamp,
                    value=close, source=source, fetched_at=fetched, status=MetricStatus.OK,
                    metadata={"effective_date": row["Date"], "proxy": "SPOT_PROXY"}))
            if result:
                return result
        except Exception:
            pass
        # Yahoo chart is used only after Stooq returns no usable observations.
        for symbol, price_type in YAHOO[self.asset]:
            fallback_source = f"Yahoo Finance {symbol} {price_type.lower().replace('_', ' ')}"
            try:
                response = self.client.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
                    params={"period1": int(datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc).timestamp()),
                            "period2": int(datetime.combine(end_date + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc).timestamp()), "interval": "1d"})
                response.raise_for_status(); payload = response.json()["chart"]["result"][0]
                closes = payload["indicators"]["quote"][0]["close"]; result = []
                for epoch, close in zip(payload["timestamp"], closes):
                    if close is None: continue
                    timestamp = datetime.fromtimestamp(epoch, timezone.utc)
                    result.append(MetricPoint(metric_name=f"{self.asset}_price_usd", timestamp=timestamp,
                        value=float(close), source=fallback_source, fetched_at=datetime.now(timezone.utc), status=MetricStatus.OK,
                        metadata={"effective_date": timestamp.date().isoformat(), "price_type": price_type, "symbol": symbol}))
                if result: return result
            except Exception:
                continue
        return [unavailable(f"{self.asset}_price_usd", "Stooq + Yahoo fallback chain", MetricStatus.UNAVAILABLE)]

    def fetch_latest(self) -> list[MetricPoint]:
        today = datetime.now(timezone.utc).date()
        return self.fetch_history(today - timedelta(days=10), today)[-1:]
