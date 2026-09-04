"""BTC/USD daily closes from public, API-key-free exchange APIs."""
from datetime import date, datetime, time, timedelta, timezone

from .base import HTTPCollector, MetricPoint, MetricStatus, unavailable


class BTCPriceCollector(HTTPCollector):
    """Use Kraken OHLC first and Coinbase Exchange candles as fallback.

    Both are public market-data endpoints.  Kraken returns at most 720 candles;
    Coinbase permits 300 candles per request, so the fallback is paginated.
    No synthetic prices are emitted when both providers fail.
    """

    KRAKEN = "https://api.kraken.com/0/public/OHLC"
    COINBASE = "https://api.exchange.coinbase.com/products/BTC-USD/candles"

    @staticmethod
    def _point(timestamp: datetime, value: object, source: str, fetched: datetime) -> MetricPoint:
        return MetricPoint(metric_name="btc_price_usd", timestamp=timestamp, value=float(value),
                           source=source, fetched_at=fetched, status=MetricStatus.OK)

    def _kraken(self, start_date: date, end_date: date) -> list[MetricPoint]:
        payload = self._get_json(self.KRAKEN, params={"pair": "XBTUSD", "interval": 1440,
            "since": int(datetime.combine(start_date, time.min, timezone.utc).timestamp())})
        if payload.get("error"):
            raise ValueError(f"Kraken API error: {payload['error']}")
        rows = next((v for k, v in payload.get("result", {}).items() if k != "last"), [])
        fetched = datetime.now(timezone.utc)
        result = [self._point(datetime.fromtimestamp(row[0], timezone.utc), row[4],
                             "Kraken Spot XBT/USD daily OHLC", fetched) for row in rows]
        return [p for p in result if start_date <= p.timestamp.date() <= end_date]

    def _coinbase(self, start_date: date, end_date: date) -> list[MetricPoint]:
        fetched = datetime.now(timezone.utc); cursor = start_date; points = []
        while cursor <= end_date:
            chunk_end = min(end_date, cursor + timedelta(days=298))
            rows = self._get_json(self.COINBASE, params={"granularity": 86400,
                "start": datetime.combine(cursor, time.min, timezone.utc).isoformat(),
                "end": datetime.combine(chunk_end + timedelta(days=1), time.min, timezone.utc).isoformat()})
            points.extend(self._point(datetime.fromtimestamp(row[0], timezone.utc), row[4],
                                      "Coinbase Exchange BTC-USD daily candles", fetched) for row in rows)
            cursor = chunk_end + timedelta(days=1)
        unique = {p.timestamp.date(): p for p in points if start_date <= p.timestamp.date() <= end_date}
        return [unique[d] for d in sorted(unique)]

    def fetch_history(self, start_date: date, end_date: date) -> list[MetricPoint]:
        for fetch in (self._kraken, self._coinbase):
            try:
                points = fetch(start_date, end_date)
                if points:
                    return points
            except Exception:
                continue
        return [unavailable("btc_price_usd", "Kraken / Coinbase Exchange", MetricStatus.UNAVAILABLE)]

    def fetch_latest(self) -> list[MetricPoint]:
        today = datetime.now(timezone.utc).date()
        return self.fetch_history(today - timedelta(days=2), today)[-1:]
