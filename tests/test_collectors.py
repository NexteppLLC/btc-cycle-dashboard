from datetime import date
import httpx
from collectors.btc_price import BTCPriceCollector
from collectors.coinmetrics import CoinMetricsCollector
from collectors.glassnode import GlassnodeCollector
from collectors.base import MetricStatus
from collectors.onchain import OnChainCollector

def client(handler): return httpx.Client(transport=httpx.MockTransport(handler))

def test_coinmetrics_success():
    c = CoinMetricsCollector(client=client(lambda r: httpx.Response(200, json={"data":[{"time":"2026-01-01T00:00:00Z","PriceUSD":"90000"}]})))
    points = c.fetch_history(date(2026,1,1), date(2026,1,1)); assert points[0].value == 90000; assert points[0].status == MetricStatus.OK

def test_api_error_is_data_not_exception():
    c = CoinMetricsCollector(client=client(lambda r: httpx.Response(500, json={})), retries=1)
    assert c.fetch_latest()[0].status == MetricStatus.ERROR

def test_missing_value_not_zero():
    c = CoinMetricsCollector(client=client(lambda r: httpx.Response(200, json={"data":[{"time":"2026-01-01T00:00:00Z","PriceUSD":None}]})))
    p = c.fetch_history(date(2026,1,1), date(2026,1,1))[0]; assert p.value is None; assert p.status == MetricStatus.MISSING

def test_glassnode_without_key():
    assert all(p.status == MetricStatus.UNAVAILABLE_NO_API_KEY and p.value is None for p in GlassnodeCollector(None).fetch_latest())

def test_global_mvrv_calculation():
    payload={"data":[{"time":"2026-01-01T00:00:00Z","CapMrktCurUSD":"900","CapRealUSD":"300","SplyCur":"10"}]}
    points=OnChainCollector(client=client(lambda r: httpx.Response(200,json=payload))).fetch_history(date(2026,1,1),date(2026,1,1))
    mvrv=next(p for p in points if p.metric_name=="global_mvrv")
    assert mvrv.value==3 and mvrv.source=="CALCULATED_FROM_MARKET_CAP_REALIZED_CAP"

def test_glassnode_plan_error():
    c=GlassnodeCollector("not-logged",client=client(lambda r:httpx.Response(403,json={})),retries=1)
    assert all(p.status==MetricStatus.UNAVAILABLE_PLAN for p in c.fetch_latest())
