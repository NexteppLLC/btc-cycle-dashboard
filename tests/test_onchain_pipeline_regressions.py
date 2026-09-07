"""Collection → saved history → current-input regressions for on-chain data."""
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from collectors.base import MetricPoint, MetricStatus
from collectors.glassnode import GlassnodeCollector
from collectors.onchain import OnChainCollector
from database.repository import Repository
from database.session import create_schema, session_scope
from services.data_quality import current_metric_row, latest_metric_record, metric_current, metric_series, observation_date, selected_metric_rows
from services.update_service import build_btc_inputs


def client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def saved_rows(url, points):
    with session_scope(url) as session:
        Repository(session).upsert_metrics(points)
    with session_scope(url) as session:
        return Repository(session).metrics()


@pytest.mark.parametrize("failure,status", [
    ("403", MetricStatus.UNAVAILABLE_PLAN),
    ("404", MetricStatus.UNAVAILABLE),
    ("empty", MetricStatus.MISSING),
    ("no_key", MetricStatus.UNAVAILABLE_NO_API_KEY),
])
@pytest.mark.parametrize("legacy_alias", [False, True])
def test_glassnode_failure_blocks_saved_cohort_values_and_successful_retry_recovers(tmp_path, failure, status, legacy_alias):
    today = datetime.now(timezone.utc).date()
    yesterday = today - timedelta(days=1)
    stamp = datetime.combine(yesterday, datetime.min.time(), timezone.utc)

    def success(request):
        value = 80000 if request.url.path.endswith("price_usd_close") else 2
        return httpx.Response(200, json=[{"t": int(stamp.timestamp()), "v": value}])

    collector = GlassnodeCollector("fixture", client=client(success))
    url = f"sqlite:///{tmp_path / 'cohorts.db'}"
    create_schema(url)
    saved_rows(url, collector.fetch_history(yesterday, today))
    if failure == "no_key":
        collector.api_key = None
    else:
        collector.client = client(lambda _: httpx.Response(200, json=[]) if failure == "empty"
                                  else httpx.Response(int(failure)))
    failed = collector.fetch_history(yesterday, today)
    cohort_names = ("lth_mvrv", "lth_realized_price")
    for name in cohort_names:
        point = next(point for point in failed if point.metric_name == name)
        assert point.status == status
        assert point.source == (GlassnodeCollector.LTH_PRICE_SOURCE if name == "lth_realized_price"
                                else GlassnodeCollector.SOURCE) + " availability"
    if legacy_alias:
        failed = [point.model_copy(update={"source": "Glassnode"}) for point in failed]
    rows = saved_rows(url, failed)
    values, _, _ = build_btc_inputs(rows, today)
    for name in cohort_names:
        assert values[name] is None
        assert current_metric_row(rows, name, today) is None
        assert len(selected_metric_rows(rows, name, today)) == 1  # preserve measured history

    # A recovered API may still publish only yesterday's completed daily data.
    # The prior request diagnostic must not strand the series until tomorrow.
    collector.api_key = "fixture"
    collector.client = client(success)
    rows = saved_rows(url, collector.fetch_history(yesterday, today))
    values, _, _ = build_btc_inputs(rows, today)
    assert values["lth_mvrv"] == 2
    assert values["lth_realized_price"] == 40000
    assert observation_date(current_metric_row(rows, "lth_mvrv", today)) == yesterday
    assert metric_current(rows, "lth_mvrv", today + timedelta(days=3)) is None
    expired = latest_metric_record(rows, "lth_mvrv", today + timedelta(days=3))
    assert expired.status == "OK" and expired.value == 2  # health reports stale, not the old failure


@pytest.mark.parametrize("legacy_alias", [False, True])
def test_same_day_glassnode_failure_preserves_saved_observations_for_charts(tmp_path, legacy_alias):
    today = datetime.now(timezone.utc).date()
    stamp = datetime.combine(today, datetime.min.time(), timezone.utc)

    def success(request):
        value = 80000 if request.url.path.endswith("price_usd_close") else 2
        return httpx.Response(200, json=[{"t": int(stamp.timestamp()), "v": value}])

    collector = GlassnodeCollector("fixture", client=client(success))
    url = f"sqlite:///{tmp_path / 'same-day.db'}"
    create_schema(url)
    saved_rows(url, collector.fetch_history(today, today))
    collector.client = client(lambda _: httpx.Response(403))
    failed = collector.fetch_history(today, today)
    if legacy_alias:
        failed = [point.model_copy(update={"source": "Glassnode"}) for point in failed]
    rows = saved_rows(url, failed)
    for name, expected in (("lth_mvrv", 2), ("lth_realized_price", 40000)):
        persisted = [row for row in rows if row.metric_name == name]
        assert len(persisted) == 2
        assert any(row.value == expected and row.status == "OK" for row in persisted)
        assert metric_current(rows, name, today) is None
        assert latest_metric_record(rows, name, today).status == "UNAVAILABLE_PLAN"
        assert metric_series(rows, name, today).isna().all()
        history = selected_metric_rows(rows, name, today)
        assert len(history) == 1 and history[0].value == expected


def test_chart_history_does_not_resurrect_explicit_same_day_missing_observation(tmp_path):
    today = datetime.now(timezone.utc).date()
    stamp = datetime.combine(today, datetime.min.time(), timezone.utc)
    collector = GlassnodeCollector("fixture", client=client(lambda _: httpx.Response(
        200, json=[{"t": int(stamp.timestamp()), "v": 2}])))
    url = f"sqlite:///{tmp_path / 'explicit-gap.db'}"
    create_schema(url)
    saved_rows(url, collector._fetch_metric("lth_mvrv", today, today))
    collector.client = client(lambda _: httpx.Response(200, json=[{"t": int(stamp.timestamp()), "v": None}]))
    rows = saved_rows(url, collector._fetch_metric("lth_mvrv", today, today))
    assert len(rows) == 1 and rows[0].status == "MISSING"
    assert selected_metric_rows(rows, "lth_mvrv", today) == []
    assert metric_current(rows, "lth_mvrv", today) is None


def test_newer_download_does_not_clear_a_missing_glassnode_observation():
    today = datetime.now(timezone.utc).date()
    midnight = datetime.combine(today, datetime.min.time(), timezone.utc)
    rows = [MetricPoint(metric_name="lth_mvrv", timestamp=midnight - timedelta(days=1), value=2,
                        source=GlassnodeCollector.SOURCE, fetched_at=midnight + timedelta(hours=2),
                        status=MetricStatus.OK),
            MetricPoint(metric_name="lth_mvrv", timestamp=midnight, value=None,
                        source=GlassnodeCollector.SOURCE, fetched_at=midnight + timedelta(hours=1),
                        status=MetricStatus.MISSING)]
    assert metric_current(rows, "lth_mvrv", today) is None


def test_derived_lth_price_retains_price_endpoint_plan_failure():
    today = datetime.now(timezone.utc).date()
    yesterday = today - timedelta(days=1)
    stamp = datetime.combine(yesterday, datetime.min.time(), timezone.utc)

    def handler(request):
        if request.url.path.endswith("price_usd_close"):
            return httpx.Response(403)
        return httpx.Response(200, json=[{"t": int(stamp.timestamp()), "v": 2}])

    points = GlassnodeCollector("fixture", client=client(handler)).fetch_history(yesterday, today)
    derived = next(point for point in points if point.metric_name == "lth_realized_price")
    assert derived.status == MetricStatus.UNAVAILABLE_PLAN
    assert derived.source == GlassnodeCollector.LTH_PRICE_SOURCE + " availability"
    assert derived.metadata["error"] == "HTTP 403"


def test_latest_missing_lth_input_blocks_derived_current_value_but_retains_history():
    today = datetime.now(timezone.utc).date()
    yesterday = today - timedelta(days=1)
    stamp = datetime.combine(yesterday, datetime.min.time(), timezone.utc)

    def handler(request):
        value = 80000 if request.url.path.endswith("price_usd_close") else 2
        latest = None if request.url.path.endswith("mvrv_more_155") else value
        return httpx.Response(200, json=[{"t": int(stamp.timestamp()), "v": value},
                                        {"t": int((stamp + timedelta(days=1)).timestamp()), "v": latest}])

    points = GlassnodeCollector("fixture", client=client(handler)).fetch_history(yesterday, today)
    assert metric_current(points, "lth_mvrv", today) is None
    assert metric_current(points, "lth_realized_price", today) is None
    derived_history = selected_metric_rows(points, "lth_realized_price", today)
    assert len(derived_history) == 1 and derived_history[0].value == 40000


def coinmetrics_history(today, observed_day, *, latest_raw=None):
    payload = {"data": [
        {"asset": "btc", "time": observed_day.isoformat() + "T00:00:00Z", "PriceUSD": "60",
         "CapMVRVCur": "2", "CapMrktCurUSD": "600", "SplyCur": "10"},
        {"asset": "btc", "time": today.isoformat() + "T00:00:00Z", "CapMVRVCur": latest_raw},
    ]}
    return OnChainCollector(client=client(lambda _: httpx.Response(200, json=payload)))


def test_unpublished_current_day_preserves_last_observed_mvrv_through_saved_pipeline(tmp_path):
    today = datetime.now(timezone.utc).date()
    yesterday = today - timedelta(days=1)
    collector = coinmetrics_history(today, yesterday)
    points = collector.fetch_history(yesterday, today)
    pending = next(point for point in points if point.metric_name == "global_mvrv"
                   and point.timestamp.date() == today)
    assert pending.status == MetricStatus.PENDING and pending.value is None
    url = f"sqlite:///{tmp_path / 'published.db'}"
    create_schema(url)
    rows = saved_rows(url, points)
    latest = next(point for point in collector.fetch_latest() if point.metric_name == "global_mvrv")
    values, _, _ = build_btc_inputs(rows, today)
    assert values["global_mvrv"] == latest.value == 2
    assert values["realized_price"] == 30
    assert observation_date(current_metric_row(rows, "global_mvrv", today)) == yesterday
    assert list(metric_series(rows, "global_mvrv", today).index) == [yesterday]
    # Once that day becomes historical, its still-unpublished cell is a gap.
    assert metric_current(rows, "global_mvrv", today + timedelta(days=1)) is None


def test_unpublished_day_does_not_bypass_observation_freshness(tmp_path):
    today = datetime.now(timezone.utc).date()
    old = today - timedelta(days=4)
    collector = coinmetrics_history(today, old)
    url = f"sqlite:///{tmp_path / 'old.db'}"
    create_schema(url)
    rows = saved_rows(url, collector.fetch_history(old, today))
    assert metric_current(rows, "global_mvrv", today) is None
    assert build_btc_inputs(rows, today)[0]["global_mvrv"] is None


@pytest.mark.parametrize("missing_day_offset,raw,status", [
    (1, None, MetricStatus.MISSING),
    (0, "NaN", MetricStatus.ERROR),
])
def test_historical_missing_and_invalid_current_observations_still_block(missing_day_offset, raw, status):
    today = datetime.now(timezone.utc).date()
    missing_day = today - timedelta(days=missing_day_offset)
    observed_day = missing_day - timedelta(days=1)
    collector = coinmetrics_history(missing_day, observed_day, latest_raw=raw)
    points = collector.fetch_history(observed_day, today)
    missing = next(point for point in points if point.metric_name == "global_mvrv"
                   and point.timestamp.date() == missing_day)
    assert missing.status == status
    assert metric_current(points, "global_mvrv", today) is None
