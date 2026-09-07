"""Provider-contract regressions for measured on-chain collection."""
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest

from collectors.base import MetricPoint, MetricStatus
from collectors.coinmetrics import CoinMetricsCollector
from collectors.glassnode import GlassnodeCollector
from collectors.onchain import OnChainCollector

DAY = date(2026, 6, 1)
STAMP = datetime(2026, 6, 1, tzinfo=timezone.utc)


def client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def point(name, value, *, timestamp=STAMP, status=MetricStatus.OK):
    return MetricPoint(metric_name=name, timestamp=timestamp, value=value,
        source="measured fixture", fetched_at=STAMP, status=status, metadata={"asset": "BTC"})


def test_free_mvrv_request_does_not_include_restricted_realized_cap():
    def handler(request):
        assert "CapMVRVCur" in request.url.params["metrics"].split(",")
        assert "CapRealUSD" not in request.url.params["metrics"].split(",")
        assert request.url.params["ignore_forbidden_errors"] == "true"
        return httpx.Response(200, json={"data": [{"asset": "btc", "time": STAMP.isoformat(),
            "PriceUSD": "71328.7312172998", "CapMVRVCur": "1.321374781897173082"}]})
    points = CoinMetricsCollector(client=client(handler)).fetch_history(DAY, DAY)
    mvrv = next(p for p in points if p.metric_name == "global_mvrv")
    assert mvrv.value == pytest.approx(1.321374781897173)
    assert mvrv.source == "Coin Metrics Community API v4"
    assert next(p for p in points if p.metric_name == "market_cap_usd").status == MetricStatus.MISSING


def test_pagination_preserves_params_and_sorts_provider_pages():
    requests = []
    def handler(request):
        requests.append(request)
        assert request.url.host == "community-api.coinmetrics.io"
        assert request.url.params["assets"] == "btc"
        if "next_page_token" not in request.url.params:
            return httpx.Response(200, json={"data": [{"time": "2026-06-02T00:00:00Z", "PriceUSD": "20"}],
                "next_page_url": "https://unrelated.invalid/?next_page_token=older"})
        assert request.url.params["next_page_token"] == "older"
        return httpx.Response(200, json={"data": [{"time": STAMP.isoformat(), "PriceUSD": "10"}]})
    points = CoinMetricsCollector(client=client(handler)).fetch_history(DAY, DAY + timedelta(days=1))
    assert [p.value for p in points if p.metric_name == "btc_price_usd"] == [10, 20]
    assert len(requests) == 2


def test_later_page_failure_keeps_successful_observations():
    def handler(request):
        if "next_page_token" in request.url.params:
            return httpx.Response(503)
        return httpx.Response(200, json={"data": [{"time": STAMP.isoformat(), "CapMVRVCur": "2"}],
            "next_page_token": "older"})
    points = CoinMetricsCollector(client=client(handler), retries=1).fetch_history(DAY, DAY)
    assert any(p.metric_name == "global_mvrv" and p.value == 2 for p in points)
    assert any(p.metric_name == "global_mvrv" and p.status == MetricStatus.ERROR for p in points)


def test_repeated_pagination_token_stops_without_discarding_data():
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"data": [{"time": STAMP.isoformat(), "PriceUSD": "10"}],
            "next_page_token": "same"})
    points = CoinMetricsCollector(client=client(handler)).fetch_history(DAY, DAY)
    assert len(requests) == 2
    assert sum(p.metric_name == "btc_price_usd" and p.value == 10 for p in points) == 1
    assert any(p.status == MetricStatus.ERROR for p in points)


@pytest.mark.parametrize("raw", ["NaN", "Infinity", "-Infinity", "not-a-number", "-1", "0", {}])
def test_invalid_mvrv_does_not_poison_other_fields(raw):
    payload = {"data": [{"time": STAMP.isoformat(), "PriceUSD": "80000", "CapMVRVCur": raw}]}
    points = CoinMetricsCollector(client=client(lambda _: httpx.Response(200, json=payload))).fetch_history(DAY, DAY)
    assert next(p for p in points if p.metric_name == "btc_price_usd").value == 80000
    mvrv = next(p for p in points if p.metric_name == "global_mvrv")
    assert mvrv.value is None and mvrv.status == MetricStatus.ERROR


@pytest.mark.parametrize("payload,status", [({"data": []}, MetricStatus.MISSING), ({"error": "bad schema"}, MetricStatus.ERROR)])
def test_empty_or_invalid_response_has_named_metric_diagnostics(payload, status):
    points = CoinMetricsCollector(client=client(lambda _: httpx.Response(200, json=payload))).fetch_history(DAY, DAY)
    assert {p.metric_name for p in points} == set(CoinMetricsCollector.FIELDS.values())
    assert all(p.value is None and p.status == status for p in points)


def test_bad_timestamps_assets_and_outside_dates_are_omitted():
    payload = {"data": [{"time": "bad", "PriceUSD": "1"},
        {"asset": "eth", "time": STAMP.isoformat(), "PriceUSD": "2"},
        {"time": "2026-05-31T00:00:00Z", "PriceUSD": "3"},
        {"time": STAMP.isoformat(), "PriceUSD": "4", "TxCnt": "0"}]}
    points = CoinMetricsCollector(client=client(lambda _: httpx.Response(200, json=payload))).fetch_history(DAY, DAY)
    assert [p.value for p in points if p.metric_name == "btc_price_usd"] == [4]
    assert next(p for p in points if p.metric_name == "transaction_count").value == 0


def test_connection_failure_is_retried(monkeypatch):
    calls = []
    monkeypatch.setattr("collectors.base.time.sleep", lambda _: None)
    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            raise httpx.ConnectError("unreachable", request=request)
        return httpx.Response(200, json={"data": [{"time": STAMP.isoformat(), "CapMVRVCur": "2"}]})
    points = CoinMetricsCollector(client=client(handler), retries=2).fetch_history(DAY, DAY)
    assert len(calls) == 2
    assert next(p for p in points if p.metric_name == "global_mvrv").value == 2


def test_latest_includes_completed_day_when_today_is_not_published():
    today = datetime.now(timezone.utc).date()
    yesterday = today - timedelta(days=1)
    def handler(request):
        assert date.fromisoformat(request.url.params["start_time"]) <= yesterday
        return httpx.Response(200, json={"data": [{"time": yesterday.isoformat() + "T00:00:00Z", "CapMVRVCur": "2"},
            {"time": today.isoformat() + "T00:00:00Z", "CapMVRVCur": None}]})
    latest = OnChainCollector(client=client(handler)).fetch_latest()
    mvrv = next(p for p in latest if p.metric_name == "global_mvrv")
    assert mvrv.value == 2 and mvrv.timestamp.date() == yesterday


def test_cap_identity_replaces_missing_direct_mvrv_without_cohort_estimates():
    collector = OnChainCollector()
    collector.upstream.fetch_history = lambda *_: [point("market_cap_usd", 900),
        point("realized_cap_usd", 300), point("btc_supply", 10), point("global_mvrv", None, status=MetricStatus.MISSING)]
    points = collector.fetch_history(DAY, DAY)
    mvrv = [p for p in points if p.metric_name == "global_mvrv"]
    assert len(mvrv) == 1 and mvrv[0].value == 3
    assert mvrv[0].source == "CALCULATED_FROM_MARKET_CAP_REALIZED_CAP"
    assert next(p for p in points if p.metric_name == "realized_price").value == 30
    assert not any(p.metric_name.startswith(("lth_", "sth_")) for p in points)


def test_no_cross_date_or_failed_status_derivations():
    collector = OnChainCollector()
    collector.upstream.fetch_history = lambda *_: [point("market_cap_usd", 900),
        point("global_mvrv", 3, timestamp=STAMP + timedelta(days=1)),
        point("realized_cap_usd", 300, status=MetricStatus.ERROR), point("btc_supply", 0)]
    points = collector.fetch_history(DAY, DAY + timedelta(days=1))
    assert not any(p.value is not None and p.source.startswith("CALCULATED_") for p in points)


def test_glassnode_correct_routes_and_same_timestamp_lth_identity():
    requested = []
    def handler(request):
        path = request.url.path.removeprefix("/v1/metrics/")
        requested.append(path)
        values = {"market/mvrv_more_155": 4, "market/price_usd_close": 80000,
            "market/price_realized_less_155_usd": 60000}
        return httpx.Response(200, json=[{"t": int(STAMP.timestamp()), "v": values.get(path, 1)}])
    points = GlassnodeCollector("fixture", client=client(handler)).fetch_history(DAY, DAY)
    assert "market/mvrv_less_155" in requested
    assert "transactions/transfers_volume_entity_adjusted_from_lth_sum" in requested
    assert "transactions/transfers_volume_entity_adjusted_from_sth_sum" in requested
    assert "indicators/realized_profit_lth_account_based" in requested
    assert "indicators/realized_loss_lth_account_based" in requested
    lth = next(p for p in points if p.metric_name == "lth_realized_price")
    assert lth.value == 20000
    assert lth.source == "CALCULATED_FROM_GLASSNODE_PRICE_LTH_MVRV"
    assert next(p for p in points if p.metric_name == "sth_realized_price").value == 60000


def test_glassnode_lth_identity_requires_aligned_price():
    def handler(request):
        timestamp = STAMP + timedelta(days=1) if request.url.path.endswith("price_usd_close") else STAMP
        return httpx.Response(200, json=[{"t": int(timestamp.timestamp()), "v": 2}])
    points = GlassnodeCollector("fixture", client=client(handler)).fetch_history(DAY, DAY + timedelta(days=1))
    assert next(p for p in points if p.metric_name == "lth_realized_price").value is None


def test_glassnode_bad_row_does_not_discard_valid_history():
    payload = [{"t": int(STAMP.timestamp()), "v": 2}, {"t": "bad", "v": 8},
        {"t": int((STAMP + timedelta(days=1)).timestamp()), "v": "NaN"}]
    collector = GlassnodeCollector("fixture", client=client(lambda _: httpx.Response(200, json=payload)))
    points = collector._fetch_metric("global_mvrv", DAY, DAY + timedelta(days=1))
    assert [p.value for p in points] == [2, None]
    assert points[-1].status == MetricStatus.ERROR


def test_glassnode_empty_response_is_explicitly_missing():
    collector = GlassnodeCollector("fixture", client=client(lambda _: httpx.Response(200, json=[])))
    points = collector._fetch_metric("global_mvrv", DAY, DAY)
    assert len(points) == 1 and points[0].status == MetricStatus.MISSING


def test_glassnode_blank_key_performs_no_http_requests():
    requests = []
    collector = GlassnodeCollector("  ", client=client(lambda request: requests.append(request)))
    points = collector.fetch_latest()
    assert not requests
    assert "lth_realized_price" in {p.metric_name for p in points}
    assert all(p.value is None and p.status == MetricStatus.UNAVAILABLE_NO_API_KEY for p in points)
