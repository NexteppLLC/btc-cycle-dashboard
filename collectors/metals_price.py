"""Daily precious-metal USD spot proxy prices from Stooq CSV."""
import csv
import io
from datetime import date, datetime, timedelta, timezone

from collectors.base import HTTPCollector, MetricPoint, MetricStatus, unavailable

SYMBOLS = {"gold": "xauusd", "silver": "xagusd"}


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
            return result or [unavailable(f"{self.asset}_price_usd", source, MetricStatus.UNAVAILABLE)]
        except Exception:
            return [unavailable(f"{self.asset}_price_usd", source, MetricStatus.UNAVAILABLE)]

    def fetch_latest(self) -> list[MetricPoint]:
        today = datetime.now(timezone.utc).date()
        return self.fetch_history(today - timedelta(days=10), today)[-1:]
