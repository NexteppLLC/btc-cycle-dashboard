from datetime import date, datetime, timezone
import httpx
import pytest

import collectors.metals_price as metals_module
from collectors.base import MetricStatus
from collectors.metals_price import MetalsPriceCollector


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def _chart(close=40.0):
    return {"chart": {"result": [{"timestamp": [1788220800], "indicators": {"quote": [{"close": [close]}]}}], "error": None}}


def test_yahoo_spot_success_stops_fallback():
    calls = []
    def handler(request):
        calls.append(str(request.url)); return httpx.Response(200, json=_chart())
    point = MetalsPriceCollector("silver", client=_client(handler)).fetch_history(date(2026,9,1), date(2026,9,1))[0]
    assert point.value == 40 and point.metadata["price_type"] == "SPOT" and len(calls) == 1


def test_yahoo_failures_fall_back_to_etf_proxy():
    def handler(request):
        return httpx.Response(200, json=_chart(35)) if "/SLV" in str(request.url) else httpx.Response(404)
    point = MetalsPriceCollector("silver", client=_client(handler), retries=1).fetch_history(date(2026,9,1), date(2026,9,1))[0]
    assert point.value == 35 and point.metadata["price_type"] == "ETF_PROXY"
    assert point.metadata["unit"] == "USD/share"
    assert point.metadata["symbol"] == "SLV"
    assert point.metadata["source_url"].endswith("/SLV")


def test_no_fabricated_metal_price():
    point = MetalsPriceCollector("gold", client=_client(lambda _: httpx.Response(404)), retries=1).fetch_history(date(2026,9,1), date(2026,9,1))[0]
    assert point.value is None and point.status == MetricStatus.UNAVAILABLE


@pytest.mark.parametrize("invalid", [None, True, "NaN", "Infinity", "-Infinity", "0", "-5", "invalid"])
def test_invalid_spot_price_uses_labelled_futures_fallback(invalid):
    def handler(request):
        return httpx.Response(200, json=_chart(invalid if "XAGUSD" in str(request.url) else 40))

    point = MetalsPriceCollector("silver", client=_client(handler)).fetch_history(date(2026, 9, 1), date(2026, 9, 1))[0]
    assert point.value == 40
    assert point.metadata["price_type"] == "FUTURES_PROXY"
    assert point.metadata["symbol"] == "SI=F"
    assert point.metadata["unit"] == "USD/troy oz"
    assert point.metadata["candle_status"] == "CLOSED"


def test_current_exchange_date_is_not_a_completed_daily_close(monkeypatch):
    # UTC has rolled over, but the current New York date is still September 1.
    now = datetime(2026, 9, 2, 0, 5, tzinfo=timezone.utc)

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz) if tz else now.replace(tzinfo=None)

    monkeypatch.setattr(metals_module, "datetime", FrozenDateTime)
    epochs = [int(datetime(2026, month, day, 13, 30, tzinfo=timezone.utc).timestamp())
              for month, day in [(8, 31), (9, 1)]]
    payload = _chart()
    payload["chart"]["result"][0].update({"meta": {"exchangeTimezoneName": "America/New_York"},
        "timestamp": epochs, "indicators": {"quote": [{"close": [35, 36]}]}})
    points = MetalsPriceCollector("silver", symbols=[("SLV", "ETF_PROXY")],
        client=_client(lambda _: httpx.Response(200, json=payload))).fetch_history(date(2026, 8, 31), date(2026, 9, 2))
    assert len(points) == 1
    assert points[0].metadata["effective_date"] == "2026-08-31"
    assert points[0].value == 35


def test_metals_drop_malformed_rows_and_sort_unique_dates():
    epoch = 1788220800
    payload = _chart()
    payload["chart"]["result"][0].update({
        "timestamp": [epoch + 86400, epoch, "invalid", epoch, epoch + 2 * 86400],
        "indicators": {"quote": [{"close": [41, 40, 42, 40.5, "NaN"]}]}})
    points = MetalsPriceCollector("silver", client=_client(lambda _: httpx.Response(200, json=payload))).fetch_history(
        date(2026, 9, 1), date(2026, 9, 3))
    assert [point.metadata["effective_date"] for point in points] == ["2026-09-01", "2026-09-02"]
    assert [point.value for point in points] == [40.5, 41]


def test_futures_overnight_session_still_open_after_midnight_is_excluded(monkeypatch):
    now = datetime(2026, 9, 2, 6, tzinfo=timezone.utc)

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz) if tz else now.replace(tzinfo=None)

    monkeypatch.setattr(metals_module, "datetime", FrozenDateTime)
    session_start = datetime(2026, 9, 1, 22, tzinfo=timezone.utc)
    session_end = datetime(2026, 9, 2, 21, tzinfo=timezone.utc)
    payload = _chart()
    payload["chart"]["result"][0].update({
        "meta": {"exchangeTimezoneName": "America/New_York", "currentTradingPeriod": {"regular": {
            "start": int(session_start.timestamp()), "end": int(session_end.timestamp())}}},
        "timestamp": [int(session_start.timestamp())]})
    point = MetalsPriceCollector("silver", symbols=[("SI=F", "FUTURES_PROXY")],
        client=_client(lambda _: httpx.Response(200, json=payload))).fetch_history(date(2026, 9, 1), date(2026, 9, 2))[0]
    assert point.value is None and point.status == MetricStatus.UNAVAILABLE


@pytest.mark.parametrize("meta", [{"currency": "EUR"}, {"symbol": "SLV"}])
def test_wrong_currency_or_instrument_is_never_reported_as_requested_spot(meta):
    def handler(request):
        payload = _chart()
        if "XAGUSD" in str(request.url):
            payload["chart"]["result"][0]["meta"] = meta
        return httpx.Response(200, json=payload)

    point = MetalsPriceCollector("silver", client=_client(handler)).fetch_history(date(2026, 9, 1), date(2026, 9, 1))[0]
    assert point.metadata["price_type"] == "FUTURES_PROXY"
    assert point.metadata["symbol"] == "SI=F"


def test_yahoo_transient_failure_retries_same_instrument(monkeypatch):
    calls = []
    monkeypatch.setattr(metals_module, "sleep", lambda _: None)

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(429) if len(calls) == 1 else httpx.Response(200, json=_chart())

    point = MetalsPriceCollector("silver", client=_client(handler), retries=2).fetch_history(date(2026, 9, 1), date(2026, 9, 1))[0]
    assert len(calls) == 2 and calls[0] == calls[1]
    assert point.metadata["price_type"] == "SPOT"
