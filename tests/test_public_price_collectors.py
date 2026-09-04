from datetime import date

import httpx

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


def test_btc_no_fabricated_value_when_both_fail():
    points = BTCPriceCollector(client=client(lambda _: httpx.Response(403)), retries=1).fetch_history(
        date(2026, 1, 1), date(2026, 1, 2))
    assert points[0].value is None and points[0].status == MetricStatus.UNAVAILABLE


def test_gold_spot_proxy_parsing():
    csv = "Date,Open,High,Low,Close\n2026-09-01,1,2,1,3500.5\n"
    points = MetalsPriceCollector("gold", client=client(lambda _: httpx.Response(200, text=csv))).fetch_history(
        date(2026, 9, 1), date(2026, 9, 1))
    assert points[0].value == 3500.5
    assert "spot proxy" in points[0].source
