"""Regressions for decision completeness with partially measured composites."""
from datetime import date, datetime, timedelta, timezone

import pytest

from scoring.cycle_score import calculate_cycle_score
from scoring.regime import classify_phase, weighted_confidence
from scoring.top_risk import calculate_top_risk
from services.health_service import build_diagnostics, metric_diagnostic
from services.update_service import build_btc_inputs, btc_input_eligibility, load_thresholds


TODAY = date(2026, 9, 7)


def point(name, value, day=TODAY, status="OK", source="Measured"):
    return {"date": day, "metric_name": name, "value": value, "status": status,
            "source": source, "fetched_at": "2026-09-07T12:00:00Z"}


def test_one_sopr_cannot_supply_full_distribution_confidence():
    rows = [point("btc_price_usd", 100+i, TODAY-timedelta(days=30-i)) for i in range(31)]
    rows += [point("lth_sopr", 2), point("mvrv_zscore", 7)]
    values, flow, coverage = build_btc_inputs(rows, TODAY)
    cfg = load_thresholds()
    eligibility = btc_input_eligibility(values, flow, coverage, cfg)
    assert values["lth_distribution"] == 100
    assert coverage == .25
    assert eligibility["confidence"] == 40
    cycle = calculate_cycle_score(values, cfg["cycle"])
    top = calculate_top_risk(values, cfg["top_risk"])
    assert classify_phase(cycle.score, top.score, values["btc_trend"], values["lth_distribution"],
                          values.get("sth_mvrv"), cfg, minimum_met=eligibility["minimum_met"],
                          confidence=eligibility["confidence"]) == "PARTIAL"
    diagnostics = build_diagnostics(rows, [], [], as_of=TODAY)
    assert diagnostics["phase_eligibility"]["btc"] == eligibility


def test_latest_etf_point_without_window_does_not_count_as_score_input():
    cfg = load_thresholds()
    values = {"btc_price_usd": 100, "btc_trend": .1}
    partial = btc_input_eligibility(values, {"today": 100, "7d": None}, 0, cfg)
    complete = btc_input_eligibility(values, {"today": 100, "7d": 700}, 0, cfg)
    assert complete["confidence"] - partial["confidence"] == 5


@pytest.mark.parametrize("coverage,expected", [(True, 100), (False, 0), (.25, 25),
                                               (float("nan"), 0), (float("inf"), 0), (-1, 0), (2, 100)])
def test_confidence_accepts_bounded_fractional_coverage(coverage, expected):
    assert weighted_confidence({"distribution": coverage}, {"distribution": 1}) == expected


def test_missing_key_explains_availability_without_failing_prices():
    rows = [point(f"{a}_price_usd", 100) for a in ("btc", "gold", "silver")]
    rows += [point("lth_mvrv", None, status="UNAVAILABLE_NO_API_KEY", source="Glassnode API v1")]
    result = build_diagnostics(rows, [], [], as_of=TODAY)
    assert result["essential_failures"] == []
    assert result["status"] == "degraded"
    state = result["sources"]["lth_mvrv"]
    assert state["status"] == "UNAVAILABLE_NO_API_KEY"
    assert "未設定" in state["reason"]
    assert state["effective_date"] is None  # failed fetch date is not an observation


def test_stale_observation_diagnostic_preserves_its_true_date():
    old = TODAY-timedelta(days=10)
    state = metric_diagnostic([point("lth_mvrv", 2, old)], "lth_mvrv", TODAY)
    assert state["status"] == "STALE"
    assert state["effective_date"] == old.isoformat()


def test_recovered_key_failure_does_not_reappear_when_observation_expires():
    failed_at = datetime(2026, 9, 7, 12, tzinfo=timezone.utc)
    rows = [{**point("lth_mvrv", None, status="UNAVAILABLE_NO_API_KEY", source="Glassnode"),
             "timestamp": failed_at, "fetched_at": failed_at},
            {**point("lth_mvrv", 2, TODAY-timedelta(days=1), source="Glassnode API v1"),
             "timestamp": datetime(2026, 9, 6, tzinfo=timezone.utc),
             "fetched_at": failed_at+timedelta(hours=1)}]
    assert metric_diagnostic(rows, "lth_mvrv", TODAY)["status"] == "OK"
    expired = metric_diagnostic(rows, "lth_mvrv", TODAY+timedelta(days=3))
    assert expired["status"] == "STALE"
    assert expired["effective_date"] == "2026-09-06"
