"""BTC/USD primary/fallback price collection."""
from datetime import date, datetime, timezone

from .base import HTTPCollector, MetricPoint, MetricStatus, unavailable
from .coinmetrics import CoinMetricsCollector


class BTCPriceCollector(HTTPCollector):
    """Coin Metrics primary; CoinGecko public API fallback."""

    FALLBACK = "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart/range"

    def __init__(self, *args, primary: CoinMetricsCollector | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.primary = primary or CoinMetricsCollector(client=self.client)

    def fetch_history(self, start_date: date, end_date: date) -> list[MetricPoint]:
        primary = [p for p in self.primary.fetch_history(start_date, end_date) if p.metric_name == "btc_price_usd" and p.value is not None]
        if primary:
            return primary
        try:
            payload = self._get_json(self.FALLBACK, params={"vs_currency": "usd", "from": int(datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc).timestamp()), "to": int(datetime.combine(end_date, datetime.max.time(), tzinfo=timezone.utc).timestamp())})
            fetched = datetime.now(timezone.utc)
            return [MetricPoint(metric_name="btc_price_usd", timestamp=datetime.fromtimestamp(ms / 1000, timezone.utc), value=float(value), source="CoinGecko Demo API", fetched_at=fetched, status=MetricStatus.OK) for ms, value in payload.get("prices", [])]
        except Exception:
            return [unavailable("btc_price_usd", "Coin Metrics / CoinGecko")]

    def fetch_latest(self) -> list[MetricPoint]:
        today = datetime.now(timezone.utc).date()
        return self.fetch_history(today, today)

