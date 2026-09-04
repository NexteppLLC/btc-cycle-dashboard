from datetime import date
import httpx

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


def test_no_fabricated_metal_price():
    point = MetalsPriceCollector("gold", client=_client(lambda _: httpx.Response(404)), retries=1).fetch_history(date(2026,9,1), date(2026,9,1))[0]
    assert point.value is None and point.status == MetricStatus.UNAVAILABLE
