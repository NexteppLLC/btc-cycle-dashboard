from datetime import date, datetime, time, timedelta, timezone

import httpx
import pytest

import collectors.btc_price as btc_module
from collectors.btc_price import BTCPriceCollector
from collectors.base import MetricStatus
from collectors.metals_price import MetalsPriceCollector


def client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_btc_kraken_daily_close():
    payload = {"error": [], "result": {"XXBTZUSD": [[1780272000, "1", "2", "0", "90000", "1", "1", 1]], "last": 1}}
    points = BTCPriceCollector(client=client(lambda _: httpx.Response(200, json=payload))).fetch_history(
        date(2026, 6, 1), date(2026, 6, 1))
    assert points[0].value == 90000
    assert points[0].source.startswith("Kraken")
    assert points[0].metadata["unit"] == "USD/BTC"
    assert points[0].metadata["source_url"] == BTCPriceCollector.KRAKEN
    assert points[0].metadata["candle_status"] == "CLOSED"


def test_btc_no_fabricated_value_when_both_fail():
    points = BTCPriceCollector(client=client(lambda _: httpx.Response(403)), retries=1).fetch_history(
        date(2026, 1, 1), date(2026, 1, 2))
    assert points[0].value is None and points[0].status == MetricStatus.UNAVAILABLE


def test_gold_yahoo_spot_parsing():
    payload = {"chart":{"result":[{"timestamp":[1788220800], "indicators":{"quote":[{"close":[3500.5]}]}}], "error":None}}
    points = MetalsPriceCollector("gold", client=client(lambda _: httpx.Response(200, json=payload))).fetch_history(
        date(2026, 9, 1), date(2026, 9, 1))
    assert points[0].value == 3500.5
    assert points[0].metadata["price_type"] == "SPOT"


def test_silver_yahoo_proxy_fallback_is_explicitly_labelled():
    def handler(request):
        if "XAGUSD" in str(request.url): return httpx.Response(404)
        return httpx.Response(200, json={"chart":{"result":[{"timestamp":[1788220800],
            "indicators":{"quote":[{"close":[42.5]}]}}], "error":None}})
    points = MetalsPriceCollector("silver", client=client(handler), retries=1).fetch_history(
        date(2026, 9, 1), date(2026, 9, 1))
    assert points[0].value == 42.5
    assert points[0].metadata["price_type"] == "FUTURES_PROXY"


def _epoch(day):
    return int(datetime.combine(day, time.min, timezone.utc).timestamp())


def _kraken_rows(days, close="90000"):
    return {"error": [], "result": {"XXBTZUSD": [
        [_epoch(day), "1", "2", "0", close, "1", "1", 1] for day in days], "last": 1}}


def test_btc_backfills_1500_days_beyond_kraken_limit():
    start = date(2020, 1, 1)
    days = [start + timedelta(days=i) for i in range(1500)]
    coinbase_requests = []

    def handler(request):
        if request.url.host == "api.kraken.com":
            return httpx.Response(200, json=_kraken_rows(days[-720:]))
        first = datetime.fromisoformat(request.url.params["start"]).date()
        exclusive_end = datetime.fromisoformat(request.url.params["end"]).date()
        assert (exclusive_end - first).days <= 299
        coinbase_requests.append((first, exclusive_end))
        # Coinbase can return preceding candles, duplicates, and reverse order.
        page = [day for day in days if first - timedelta(days=1) <= day <= exclusive_end]
        rows = [[_epoch(day), 1, 2, 1, 89000, 3] for day in reversed(page)]
        return httpx.Response(200, json=rows + rows[:1])

    points = BTCPriceCollector(client=client(handler)).fetch_history(days[0], days[-1])
    assert [point.timestamp.date() for point in points] == days
    assert len(coinbase_requests) == 3
    assert sum(point.source.startswith("Kraken") for point in points) == 720
    assert points[0].source.startswith("Coinbase")
    assert points[0].metadata["source_url"] == BTCPriceCollector.COINBASE
    assert all(point.metadata["history_complete"] for point in points)


@pytest.mark.parametrize("provider", ["kraken", "coinbase"])
def test_btc_excludes_current_daily_candle(monkeypatch, provider):
    now = datetime(2026, 6, 10, 12, tzinfo=timezone.utc)

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz) if tz else now.replace(tzinfo=None)

    monkeypatch.setattr(btc_module, "datetime", FrozenDateTime)
    yesterday = now.date() - timedelta(days=1)

    def handler(request):
        if request.url.host == "api.kraken.com":
            return httpx.Response(200, json=_kraken_rows([yesterday, now.date()])) if provider == "kraken" else httpx.Response(403)
        return httpx.Response(200, json=[[_epoch(day), 1, 2, 1, 89000, 3] for day in [yesterday, now.date()]])

    points = BTCPriceCollector(client=client(handler), retries=1).fetch_history(yesterday, now.date())
    assert [point.timestamp.date() for point in points] == [yesterday]
    assert points[0].metadata["history_complete"] is True


@pytest.mark.parametrize("invalid", [None, True, "NaN", "Infinity", "-Infinity", "0", "-5", "invalid"])
def test_btc_never_emits_invalid_prices(invalid):
    day = date(2026, 6, 1)

    def handler(request):
        if request.url.host == "api.kraken.com":
            return httpx.Response(200, json=_kraken_rows([day], invalid))
        return httpx.Response(200, json=[[_epoch(day), 1, 2, 1, invalid, 3]])

    point = BTCPriceCollector(client=client(handler), retries=1).fetch_history(day, day)[0]
    assert point.value is None
    assert point.status == MetricStatus.UNAVAILABLE


def test_btc_keeps_good_kraken_dates_and_fills_invalid_or_missing_dates():
    days = [date(2026, 6, day) for day in (1, 2, 3)]
    requested = []

    def handler(request):
        if request.url.host == "api.kraken.com":
            payload = _kraken_rows(days)
            payload["result"]["XXBTZUSD"][1][4] = "NaN"
            payload["result"]["XXBTZUSD"].append(["malformed"])
            return httpx.Response(200, json=payload)
        requested.append(datetime.fromisoformat(request.url.params["start"]).date())
        return httpx.Response(200, json=[[_epoch(days[1]), 1, 2, 1, 89000, 3]])

    points = BTCPriceCollector(client=client(handler)).fetch_history(days[0], days[-1])
    assert requested == [days[1]]
    assert [point.value for point in points] == [90000, 89000, 90000]
    assert all(point.metadata["history_complete"] for point in points)


def test_btc_retains_successful_pages_when_backfill_page_fails():
    start = date(2020, 1, 1)
    end = start + timedelta(days=599)

    def handler(request):
        if request.url.host == "api.kraken.com":
            return httpx.Response(403)
        first = datetime.fromisoformat(request.url.params["start"]).date()
        exclusive_end = datetime.fromisoformat(request.url.params["end"]).date()
        if first == start + timedelta(days=299):
            return httpx.Response(503)
        return httpx.Response(200, json=[[_epoch(first + timedelta(days=i)), 1, 2, 1, 89000, 3]
            for i in range((exclusive_end - first).days)])

    points = BTCPriceCollector(client=client(handler), retries=1).fetch_history(start, end)
    assert len(points) == 301
    assert points[0].timestamp.date() == start and points[-1].timestamp.date() == end
    assert points[-1].metadata["history_complete"] is False
    assert points[-1].metadata["requested_days"] == 600
    assert points[-1].metadata["available_days"] == 301
