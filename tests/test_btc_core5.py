from datetime import date, datetime, timedelta, timezone

import math
import pytest

from collectors.base import MetricPoint, MetricStatus
from collectors.glassnode import GlassnodeCollector
from indicators.btc_core import (alerts, calendar_sma, core_state, exact_change,
                                 rolling_percentile, sell_side_raw,
                                 short_term_state)
from services.report_service import report_text
from services.core5_service import build_core5
from database.repository import Repository
from database.session import create_schema, session_scope
from database.models import Metric
from types import SimpleNamespace


DAY = date(2026, 9, 20)
STAMP = datetime(2026, 9, 20, tzinfo=timezone.utc)


@pytest.mark.parametrize("values", [(None, 1, 10), (1, None, 10), (1, 1, None),
                                     (-1, 1, 10), (1, -1, 10), (1, 1, 0),
                                     (math.nan, 1, 10), (1, math.inf, 10)])
def test_sell_side_raw_rejects_missing_nonfinite_negative_and_zero_cap(values):
    assert sell_side_raw(*values) is None


def test_sell_side_raw_accepts_measured_zero_profit_and_loss():
    assert sell_side_raw(0, 0, 100) == 0
    assert sell_side_raw(2, 1, 1000) == .003


def test_sma_requires_exactly_continuous_15_calendar_days():
    values = {DAY - timedelta(days=i): .001 * (i + 1) for i in range(15)}
    assert calendar_sma(values, DAY) == pytest.approx(.008)
    values.pop(DAY - timedelta(days=8))
    assert calendar_sma(values, DAY) is None
    assert calendar_sma({DAY - timedelta(days=i): .1 for i in range(14)}, DAY) is None


def test_exact_differences_never_use_nearest_row():
    values = {DAY: 1.2, DAY - timedelta(days=2): 1.1, DAY - timedelta(days=7): 1.0}
    assert exact_change(values, DAY, 1) == (None, None)
    assert exact_change(values, DAY, 7) == pytest.approx((.2, 1.0))


def test_percentile_uses_inclusive_364_day_window_midrank_and_no_future():
    start = DAY - timedelta(days=363)
    values = {start + timedelta(days=i): 1.0 for i in range(364)}
    values[DAY + timedelta(days=1)] = 999
    result = rolling_percentile(values, DAY)
    assert result["status"] == "OK" and result["count"] == result["expected"] == 364
    assert result["start"] == start and result["end"] == DAY
    assert result["value"] == .5
    del values[start]
    assert rolling_percentile(values, DAY)["status"] == "INSUFFICIENT_HISTORY"


def test_four_year_window_has_calendar_year_endpoint():
    leap_day = date(2024, 2, 29)
    values = {leap_day - timedelta(days=i): float(i) for i in range(1462)}
    result = rolling_percentile(values, leap_day, 4)
    assert result["start"] == date(2020, 2, 29)
    assert result["expected"] == (leap_day - date(2020, 2, 29)).days + 1


def full_values(**changes):
    result = {"sth_mvrv": 1.1, "sth_sopr": 1.0, "lth_mvrv": 2.5,
              "distribution": 50, "sell_side_risk": .002, "sell_side_percentile_4y": .5}
    result.update({f"{name}_date": DAY for name in
                   ("sth_mvrv", "sth_sopr", "lth_mvrv", "distribution", "sell_side_risk")})
    result.update(changes)
    return result


@pytest.mark.parametrize(("changes", "expected"), [
    ({"distribution": 70, "lth_mvrv": 3.5}, "DISTRIBUTION_RISK"),
    ({"sth_mvrv": .9, "sth_sopr": .9, "lth_mvrv": 3.6}, "STRESS"),
    ({"lth_mvrv": 3.5}, "OVERHEATED"),
    ({"sell_side_risk": .0075, "lth_mvrv": 2}, "OVERHEATED"),
    ({"sth_mvrv": 1.01}, "HEALTHY_BULL"),
    ({"sth_mvrv": 1.0}, "RECOVERY"),
])
def test_core_state_priority_and_boundaries(changes, expected):
    assert core_state(full_values(**changes), 1.0)[0] == expected


def test_unknown_or_partial_distribution_never_becomes_healthy_or_low():
    values = full_values(sell_side_percentile_4y=None)
    assert core_state(values, 1.0)[0] == "PARTIAL"
    assert core_state(full_values(), .75)[0] == "PARTIAL"
    assert core_state(full_values(sth_mvrv_date=DAY - timedelta(days=1)), 1.0)[0] == "PARTIAL"
    assert short_term_state(None, 1.0) == "PARTIAL"


def test_individual_alerts_survive_partial_and_consecutive_requires_exact_day():
    current = {**full_values(distribution=80, lth_mvrv=3.5), "observation_date": DAY}
    history = {"sth_mvrv": {DAY - timedelta(days=1): 1.1},
               "sth_sopr": {DAY - timedelta(days=1): 1.1}}
    ids = {item["id"] for item in alerts(current, history)}
    assert {"BTC5_STH_RECOVERY", "BTC5_LTH_HEAT_HIGH", "BTC5_LTH_DISTRIBUTION_HIGH",
            "BTC5_DISTRIBUTION_RISK"} <= ids
    history = {"sth_mvrv": {DAY - timedelta(days=2): 1.1}, "sth_sopr": {DAY - timedelta(days=2): 1.1}}
    assert "BTC5_STH_RECOVERY" not in {item["id"] for item in alerts(current, history)}


def point(name, value, timestamp=STAMP, **metadata):
    return MetricPoint(metric_name=name, timestamp=timestamp, value=value, source="Glassnode API v1",
        fetched_at=STAMP, status=MetricStatus.OK,
        metadata={"asset": "BTC", "unit": "USD", "methodology": "GLASSNODE_NETWORK_REALIZED_VALUE",
                  "provider_timestamp": timestamp.isoformat(), **metadata})


def test_sell_side_derivation_rejects_misaligned_timestamp_provider_asset_unit_methodology():
    collector = GlassnodeCollector("not-a-secret")
    names = list(collector.SELL_SIDE_ENDPOINTS)
    valid = [point(name, value) for name, value in zip(names, (2, 1, 1000))]
    # Current-day exclusion uses the real clock; make the fixture safely historical.
    assert collector._sell_side_points(valid, DAY, DAY)[0].metric_name == "sell_side_risk_raw"
    mutations = [
        [valid[0], valid[1], point(names[2], 1000, STAMP + timedelta(hours=1))],
        [valid[0], valid[1], valid[2].model_copy(update={"source": "Other"})],
        [valid[0], valid[1].model_copy(update={"metadata": {**valid[1].metadata, "asset": "ETH"}}), valid[2]],
        [valid[0], valid[1].model_copy(update={"metadata": {**valid[1].metadata, "unit": "BTC"}}), valid[2]],
        [valid[0], valid[1].model_copy(update={"metadata": {**valid[1].metadata, "methodology": "OTHER"}}), valid[2]],
    ]
    for inputs in mutations:
        assert not any(p.metric_name == "sell_side_risk_raw" and p.status == MetricStatus.OK
                       for p in collector._sell_side_points(inputs, DAY, DAY))


@pytest.mark.parametrize("status_code", [401, 403])
def test_api_key_is_not_present_in_unavailable_diagnostics(status_code):
    secret = "super-secret-key"
    collector = GlassnodeCollector(secret)
    class Response: pass
    Response.status_code = status_code
    class Failure(Exception): response = Response()
    collector._get_json = lambda *args, **kwargs: (_ for _ in ()).throw(Failure())
    result = collector._fetch_metric("sell_side_realized_profit_usd", DAY, DAY,
                                     endpoint="indicators/realized_profit")
    assert result[0].status == MetricStatus.UNAVAILABLE_PLAN
    assert result[0].metadata["error"] == f"HTTP {status_code}"
    assert secret not in repr(result[0])


def test_missing_api_key_is_explicit():
    result = GlassnodeCollector(None)._fetch_metric("sell_side_realized_profit_usd", DAY, DAY,
                                                   endpoint="indicators/realized_profit")
    assert result[0].status == MetricStatus.UNAVAILABLE_NO_API_KEY


def test_report_contains_same_core_state_substates_and_alert_provenance():
    card = {"value": None, "date": None, "status": "UNAVAILABLE"}
    core = {"cards": {name: dict(card) for name in ("sth_mvrv", "sth_sopr", "lth_mvrv", "distribution", "sell_side_risk")},
            "substates": {"short_term_health": "PARTIAL", "cycle_heat": "PARTIAL", "distribution_pressure": "PARTIAL"},
            "state": "PARTIAL", "reasons": ["欠損"],
            "alerts": [{"id": "BTC5_LTH_HEAT_HIGH", "severity": "HIGH", "observation_date": DAY, "reason": "fixture"}]}
    snapshot = SimpleNamespace(date=DAY, btc_price=None, cycle_phase="PARTIAL", confidence=0,
        cycle_score=None, top_risk_score=None, global_mvrv=None, mvrv_zscore=None,
        lth_mvrv=None, sth_mvrv=None, lth_distribution=None, etf_flow_1d=None, etf_flow_7d=None)
    text = report_text(snapshot, core5=core)
    assert "BTC 5-Signal State：PARTIAL" in text
    assert "Short-Term Health：PARTIAL" in text
    assert "BTC5_LTH_HEAT_HIGH · HIGH · 観測日 2026-09-20" in text


CORE_CFG = {"distribution_minimum_coverage": 1.0, "sth_break_even": 1.0,
    "lth_mvrv": {"capitulation": 1, "low_early": 2, "high": 3.5, "extreme": 5},
    "distribution": {"low": 40, "rising": 60, "high": 70, "extreme": 80},
    "sell_side_risk": {"compression": .001, "high": .0075, "percentile_compression": .1,
                       "percentile_high": .9, "percentile_extreme": .95}}


def metric_row(name, value, day=DAY, methodology="fixture-v1", status="OK"):
    stamp = datetime.combine(day, datetime.min.time(), timezone.utc)
    return {"metric_name": name, "value": value, "date": day, "timestamp": stamp,
            "effective_date": day, "source": "fixture", "status": status,
            "fetched_at": STAMP + timedelta(hours=12), "methodology": methodology,
            "price_type": None, "error": None}


def current_core_rows(day=DAY):
    return [metric_row("sth_mvrv", 1.1, day), metric_row("sth_sopr", 1.1, day),
            metric_row("lth_mvrv", 4, day), metric_row("sell_side_risk_15d", .003, day)]


def distribution_snapshot(day=DAY, observed=DAY, value=80, coverage=1.0):
    return {"date": day, "lth_distribution": value,
            "lth_distribution_observed_date": observed,
            "lth_distribution_coverage": coverage}


def test_build_core5_keeps_independent_alerts_when_other_signals_are_missing():
    rows = [metric_row("lth_mvrv", 4)]
    result = build_core5(rows, [distribution_snapshot()], CORE_CFG, DAY)
    assert result["state"] == "PARTIAL"
    assert {item["id"] for item in result["alerts"]} == {
        "BTC5_LTH_HEAT_HIGH", "BTC5_LTH_DISTRIBUTION_HIGH", "BTC5_DISTRIBUTION_RISK"}


def test_build_core5_never_substitutes_snapshot_date_for_distribution_observation():
    result = build_core5(current_core_rows(), [distribution_snapshot(observed=None)], CORE_CFG, DAY)
    assert result["state"] == "PARTIAL"
    assert result["cards"]["distribution"]["date"] is None
    assert result["cards"]["distribution"]["value"] is None
    assert not any("DISTRIBUTION" in item["id"] for item in result["alerts"])


def test_build_core5_applies_configured_thresholds_to_states_substates_and_alerts():
    config = {**CORE_CFG, "lth_mvrv": {**CORE_CFG["lth_mvrv"], "high": 4.5}}
    result = build_core5(current_core_rows(), [distribution_snapshot(value=60)], config, DAY)
    assert result["substates"]["cycle_heat"] == "NORMAL_BULL"
    assert "BTC5_LTH_HEAT_HIGH" not in {item["id"] for item in result["alerts"]}
    assert result["state"] != "DISTRIBUTION_RISK"


def test_build_core5_proves_higher_priority_distribution_risk_without_percentile():
    result = build_core5(current_core_rows(), [distribution_snapshot()], CORE_CFG, DAY)
    assert result["cards"]["sell_side_risk"]["percentile_4y"]["value"] is None
    assert result["state"] == "DISTRIBUTION_RISK"


def test_build_core5_does_not_mix_methodologies_for_percentile():
    start = DAY - timedelta(days=363)
    rows = [metric_row("sth_mvrv", 1 + i / 1000, start + timedelta(days=i), "old") for i in range(363)]
    rows.append(metric_row("sth_mvrv", 1.5, DAY, "new"))
    result = build_core5(rows, [], CORE_CFG, DAY)
    stat = result["cards"]["sth_mvrv"]["percentile_52w"]
    assert stat["status"] == "INSUFFICIENT_HISTORY"
    assert stat["count"] == 1


def test_build_core5_marks_stale_value_with_date_and_reason_and_report_matches():
    old = DAY - timedelta(days=4)
    result = build_core5([metric_row("lth_mvrv", 4, old)], [], CORE_CFG, DAY)
    card = result["cards"]["lth_mvrv"]
    assert card["value"] is None and card["status"] == "STALE" and card["date"] == old
    assert "4暦日経過" in card["reason"]
    snapshot = SimpleNamespace(date=DAY, btc_price=None, cycle_phase="PARTIAL", confidence=0,
        cycle_score=None, top_risk_score=None, global_mvrv=None, mvrv_zscore=None,
        lth_mvrv=None, sth_mvrv=None, lth_distribution=None, etf_flow_1d=None, etf_flow_7d=None)
    text = report_text(snapshot, core5=result)
    assert f"LTH-MVRV：取得不可 · 観測日 {old} · Status STALE" in text
    assert "理由 観測日から4暦日経過" in text


def test_sell_side_missing_overwrites_saved_current_value_and_recovery_restores_it(tmp_path):
    url = f"sqlite:///{tmp_path / 'core5.db'}"
    create_schema(url)
    collector = GlassnodeCollector("fixture")
    names = list(collector.SELL_SIDE_ENDPOINTS)
    days = [DAY - timedelta(days=i) for i in range(14, -1, -1)]
    def inputs(missing_latest=False):
        rows = []
        for day in days:
            stamp = datetime.combine(day, datetime.min.time(), timezone.utc)
            for name, value in zip(names, (2, 1, 1000)):
                row = point(name, value, stamp)
                if missing_latest and day == DAY and name == names[0]:
                    row = row.model_copy(update={"value": None, "status": MetricStatus.MISSING})
                rows.append(row)
        return rows
    with session_scope(url) as session:
        repo = Repository(session)
        repo.upsert_metrics(collector._sell_side_points(inputs(), DAY, DAY))
    with session_scope(url) as session:
        assert session.query(Metric).filter_by(
            metric_name="sell_side_risk_15d", date=DAY).one().status == "OK"
        Repository(session).upsert_metrics(collector._sell_side_points(inputs(True), DAY, DAY))
    with session_scope(url) as session:
        row = session.query(Metric).filter_by(
            metric_name="sell_side_risk_15d", date=DAY).one()
        assert row.status == "MISSING" and row.value is None
        core = build_core5(Repository(session).metrics(), [], CORE_CFG, DAY)
        assert core["cards"]["sell_side_risk"]["value"] is None
        Repository(session).upsert_metrics(collector._sell_side_points(inputs(), DAY, DAY))
    with session_scope(url) as session:
        row = session.query(Metric).filter_by(
            metric_name="sell_side_risk_15d", date=DAY).one()
        assert row.status == "OK" and row.value == pytest.approx(.003)
        assert build_core5(Repository(session).metrics(), [], CORE_CFG, DAY)["cards"]["sell_side_risk"]["value"] == pytest.approx(.003)
