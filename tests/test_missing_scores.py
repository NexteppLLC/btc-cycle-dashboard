"""Regressions for unavailable observations becoming convincing market signals."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from indicators.etf import etf_aggregates
from indicators.holders import distribution_score, sth_state
from indicators.mvrv import calculate_mvrv
from indicators.normalization import change_summary, finite_number, historical_stats, minmax, multi_horizon_stats
from indicators.technical import calculate_technicals
from scoring.cycle_score import calculate_cycle_score
from scoring.regime import btc_minimum_data, calculate_confidence, classify_phase, detect_alerts
from scoring.top_risk import calculate_top_risk, risk_label

CFG = yaml.safe_load((Path(__file__).parents[1] / "config/thresholds.yaml").read_text())


@pytest.mark.parametrize("unavailable", [None, np.nan, np.inf, -np.inf, pd.NA, "unavailable"])
def test_nonfinite_inputs_do_not_become_scores_or_labels(unavailable):
    assert finite_number(unavailable) is None
    assert minmax(unavailable, 0, 100) is None
    assert risk_label(unavailable) == "判定不能"
    cycle = calculate_cycle_score({name: unavailable for name in CFG["cycle"]["weights"]}, CFG["cycle"])
    top = calculate_top_risk({name: unavailable for name in CFG["top_risk"]["weights"]}, CFG["top_risk"])
    assert (cycle.score, cycle.coverage, cycle.details) == (None, 0, [])
    assert (top.score, top.coverage, top.details) == (None, 0, [])


def test_unavailable_components_do_not_count_toward_score_coverage():
    result = calculate_cycle_score({"lth_mvrv": 2.5, "lth_distribution": np.inf, "sth_state": np.nan}, CFG["cycle"])
    assert result.score == 50
    assert result.coverage == .25
    assert [detail["component"] for detail in result.details] == ["lth_mvrv"]
    risk = calculate_top_risk({"lth_mvrv": 3.25, "etf_divergence": np.inf}, CFG["top_risk"])
    assert risk.score == 50
    assert risk.coverage == .20


@pytest.mark.parametrize("value, expected", [(-50, 0), (150, 100)])
def test_pre_normalized_components_have_score_bounds(value, expected):
    cycle = calculate_cycle_score({"lth_distribution": value, "sth_state": value}, CFG["cycle"])
    risk = calculate_top_risk({"lth_distribution": value, "etf_divergence": value}, CFG["top_risk"])
    for result in (cycle, risk):
        assert result.score == expected
        assert all(0 <= detail["normalized_score"] <= 100 for detail in result.details)


def test_normalization_rejects_invalid_bounds_and_preserves_inverse_ranges():
    assert minmax(1, 1, 1) is None
    assert minmax(1, 0, np.inf) is None
    assert minmax(-1.5, 0, -3) == 50
    assert minmax(0, -1e308, 1e308) == 50


def test_etf_latest_missing_is_not_replaced_with_previous_flow():
    result = etf_aggregates(pd.Series([1.0] * 30 + [np.nan]))
    assert all(value is None for value in result.values())


def test_etf_missing_window_rows_are_not_compressed_or_imputed():
    flows = pd.Series([1.0] * 30)
    flows.iloc[-4] = np.inf
    result = etf_aggregates(flows)
    assert result["today"] == 1
    assert result["3d"] == 3
    assert result["7d"] is None and result["avg_7d"] is None
    assert result["30d"] is None and result["avg_30d"] is None
    zeros = etf_aggregates(pd.Series([0.0] * 30))
    assert all(value == 0 for value in zeros.values())


def test_latest_missing_prevents_stale_historical_statistics():
    values = pd.Series(list(range(400)) + [np.inf])
    assert historical_stats(values) == {"percentile": None, "zscore": None}
    assert all(value is None for value in multi_horizon_stats(values).values())
    summary = change_summary(values)
    assert summary["current"] is None and summary["daily_change"] is None
    assert summary["previous"] == 399


def test_historical_windows_preserve_missing_positions():
    values = pd.Series(list(range(365)) + [np.nan] * 340 + [500])
    result = multi_horizon_stats(values)
    assert result["percentile_52w"] is None
    assert result["rolling_zscore"] is None
    assert result["percentile_all"] == 1


@pytest.mark.parametrize("unavailable", [np.nan, np.inf, -np.inf])
def test_nonfinite_inputs_cannot_pass_minimum_data_or_classify_phase(unavailable):
    met, missing = btc_minimum_data({"btc_price_usd": unavailable, "btc_trend": unavailable,
                                      "lth_mvrv": unavailable, "sth_mvrv": unavailable})
    assert not met and len(missing) == 3
    assert classify_phase(unavailable, 20, .1, 20, 1.1, CFG) == "UNKNOWN"
    assert classify_phase(50, 20, unavailable, 20, 1.1, CFG) == "UNKNOWN"
    assert classify_phase(50, 20, .1, 20, 1.1, CFG, confidence=unavailable) == "PARTIAL"
    assert calculate_confidence(coverage=unavailable, glassnode=True, etf_current=True, config=CFG) == 0


def test_nonfinite_values_do_not_trigger_alerts_or_holder_states():
    values = {"top_risk": np.inf, "lth_distribution": np.inf, "sth_mvrv": -np.inf,
              "lth_mvrv": np.inf, "mvrv_zscore": np.inf, "etf_flow_7d": -np.inf}
    assert detect_alerts(values, CFG) == []
    assert sth_state({"sth_mvrv": -np.inf, "sth_sopr": .9}) is None
    assert sth_state({"sth_mvrv": 1.1, "btc_price_usd": np.inf, "sth_realized_price": 100}) is None
    assert distribution_score({"lth_sopr": np.inf}) == (None, 0.0)


def test_mvrv_requires_finite_positive_measured_caps():
    assert calculate_mvrv(10, 5) == 2
    for market, realized in [(np.inf, 5), (10, np.nan), (10, 0), (10, -5), (-10, 5)]:
        assert calculate_mvrv(market, realized) is None


@pytest.mark.parametrize("prices, rsi", [(list(range(1, 16)), 100), (list(range(15, 0, -1)), 0), ([5] * 15, 50)])
def test_rsi_valid_one_sided_and_flat_windows(prices, rsi):
    technicals = calculate_technicals(pd.Series(prices))
    assert technicals["rsi_14"].iloc[-1] == rsi
    assert technicals["rsi_14"].iloc[:-1].isna().all()


def test_nonfinite_prices_leave_current_technicals_missing():
    prices = pd.Series(list(range(1, 401)) + [np.inf])
    technicals = calculate_technicals(prices)
    assert technicals.iloc[-1].isna().all()
    assert not np.isinf(technicals.to_numpy()).any()
