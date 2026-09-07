"""BTC/USD daily closes from public, API-key-free exchange APIs."""
from datetime import date, datetime, time, timedelta, timezone
from math import isfinite

from .base import HTTPCollector, MetricPoint, MetricStatus, unavailable


class BTCPriceCollector(HTTPCollector):
    """Use Kraken OHLC first and backfill missing dates from Coinbase.

    Both are public market-data endpoints.  Kraken returns at most 720 candles;
    Coinbase permits 300 candles per request, so the backfill is paginated.
    No synthetic prices are emitted when both providers fail.
    """

    KRAKEN = "https://api.kraken.com/0/public/OHLC"
    COINBASE = "https://api.exchange.coinbase.com/products/BTC-USD/candles"

    @staticmethod
    def _point(timestamp: datetime, value: object, source: str, fetched: datetime,
               symbol: str, source_url: str) -> MetricPoint:
        price = float(value)
        if isinstance(value, bool) or not isfinite(price) or price <= 0:
            raise ValueError("Price must be finite and positive")
        return MetricPoint(
            metric_name="btc_price_usd", timestamp=timestamp, value=price,
            source=source, fetched_at=fetched, status=MetricStatus.OK,
            metadata={"asset": "BTC", "effective_date": timestamp.date().isoformat(),
                      "price_type": "SPOT", "symbol": symbol, "unit": "USD/BTC",
                      "currency": "USD", "source_url": source_url, "candle_status": "CLOSED"},
        )

    def _parse_rows(self, rows: list, start_date: date, end_date: date, *,
                    source: str, symbol: str, source_url: str) -> list[MetricPoint]:
        fetched = datetime.now(timezone.utc)
        points = {}
        for row in rows:
            try:
                timestamp = datetime.fromtimestamp(row[0], timezone.utc)
                # A daily bucket's timestamp is its start, not its close. Kraken
                # always includes the current uncommitted bucket in its reply.
                if not start_date <= timestamp.date() <= end_date or timestamp + timedelta(days=1) > fetched:
                    continue
                point = self._point(timestamp, row[4], source, fetched, symbol, source_url)
                points[timestamp.date()] = point
            except (IndexError, KeyError, TypeError, ValueError, OverflowError, OSError):
                continue
        return [points[day] for day in sorted(points)]

    def _kraken(self, start_date: date, end_date: date) -> list[MetricPoint]:
        payload = self._get_json(self.KRAKEN, params={"pair": "XBTUSD", "interval": 1440,
            "since": int(datetime.combine(start_date, time.min, timezone.utc).timestamp())})
        if payload.get("error"):
            raise ValueError(f"Kraken API error: {payload['error']}")
        rows = next((v for k, v in payload.get("result", {}).items() if k != "last"), [])
        return self._parse_rows(rows, start_date, end_date,
                                source="Kraken Spot XBT/USD daily OHLC", symbol="XBTUSD", source_url=self.KRAKEN)

    def _coinbase(self, start_date: date, end_date: date) -> list[MetricPoint]:
        cursor = start_date
        points = []
        while cursor <= end_date:
            # Keep even an inclusive provider response within the 300-candle
            # limit. Responses may also contain dates before the requested start.
            chunk_end = min(end_date, cursor + timedelta(days=298))
            try:
                rows = self._get_json(self.COINBASE, params={"granularity": 86400,
                    "start": datetime.combine(cursor, time.min, timezone.utc).isoformat(),
                    "end": datetime.combine(chunk_end + timedelta(days=1), time.min, timezone.utc).isoformat()})
                if not isinstance(rows, list):
                    raise ValueError("Coinbase returned no candle array")
                points.extend(self._parse_rows(rows, cursor, chunk_end,
                    source="Coinbase Exchange BTC-USD daily candles", symbol="BTC-USD", source_url=self.COINBASE))
            except Exception:
                # Preserve other genuinely observed pages if one page fails.
                # fetch_history reports any remaining gaps in its metadata.
                pass
            cursor = chunk_end + timedelta(days=1)
        unique = {p.timestamp.date(): p for p in points if start_date <= p.timestamp.date() <= end_date}
        return [unique[d] for d in sorted(unique)]

    def fetch_history(self, start_date: date, end_date: date) -> list[MetricPoint]:
        # These metrics are completed daily closes; today's live quote belongs
        # to a different series and must not enter daily technical indicators.
        end_date = min(end_date, datetime.now(timezone.utc).date() - timedelta(days=1))
        points = {}
        if start_date <= end_date:
            try:
                points = {p.timestamp.date(): p for p in self._kraken(start_date, end_date)}
            except Exception:
                pass

            # Kraken's documented 720-entry limit is independent of `since`.
            # Fill every missing interval, including older history and gaps.
            cursor = start_date
            while cursor <= end_date:
                if cursor in points:
                    cursor += timedelta(days=1)
                    continue
                missing_start = cursor
                while cursor <= end_date and cursor not in points:
                    cursor += timedelta(days=1)
                for point in self._coinbase(missing_start, cursor - timedelta(days=1)):
                    points.setdefault(point.timestamp.date(), point)

        requested_days = max(0, (end_date - start_date).days + 1)
        coverage = {"history_complete": bool(points) and len(points) == requested_days,
                    "available_days": len(points), "requested_days": requested_days,
                    "history_start": start_date.isoformat(), "history_end": end_date.isoformat()}
        if points:
            for point in points.values():
                point.metadata.update(coverage)
            return [points[day] for day in sorted(points)]
        point = unavailable("btc_price_usd", "Kraken / Coinbase Exchange", MetricStatus.UNAVAILABLE)
        point.metadata = {"asset": "BTC", "unit": "USD/BTC", "currency": "USD", **coverage,
                          "error": "No valid completed daily closes available"}
        return [point]

    def fetch_latest(self) -> list[MetricPoint]:
        today = datetime.now(timezone.utc).date()
        return self.fetch_history(today - timedelta(days=2), today)[-1:]
