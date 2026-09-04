import pandas as pd

from indicators.holders import distribution_score, sth_state
from indicators.normalization import multi_horizon_stats
from scoring.regime import btc_minimum_data, weighted_confidence
from scoring.regime import classify_phase
import yaml
from pathlib import Path


def test_lth_distribution_score():
    score, coverage = distribution_score({"lth_sopr": 1.5, "cdd_z": 1.5})
    assert score == 50 and coverage == .35


def test_sth_stress():
    assert sth_state({"sth_mvrv": .9, "sth_sopr": .95}) == "STH_STRESS"
    assert sth_state({"sth_mvrv": 1.1, "btc_price_usd": 101, "sth_realized_price": 100}) == "RECOVERY_CONFIRMATION"


def test_btc_phase_partial_requirements():
    ok, missing = btc_minimum_data({"btc_price_usd": 1, "btc_trend": .1, "global_mvrv": 2})
    assert not ok and "On-chain major metrics (0/2)" in missing


def test_btc_confidence():
    weights={"price":.1,"global_mvrv":.1,"lth_mvrv":.15}
    assert weighted_confidence({"price":True,"global_mvrv":True},weights)==57.1


def test_mvrv_percentile():
    result=multi_horizon_stats(pd.Series(range(400)))
    assert result["percentile_52w"]==1 and result["percentile_4y"] is not None


def test_no_fabricated_onchain_values():
    assert sth_state({"global_mvrv": 3}) is None
    assert distribution_score({"global_mvrv": 3}) == (None, 0.0)


def test_free_mode_missing_lth():
    from collectors.glassnode import GlassnodeCollector
    assert all(p.value is None for p in GlassnodeCollector(None).fetch_latest())


def test_glassnode_adapter():
    assert "lth_mvrv" in __import__("collectors.glassnode", fromlist=["GlassnodeCollector"]).GlassnodeCollector.ENDPOINTS


def test_btc_phase_full_data():
    cfg=yaml.safe_load((Path(__file__).parents[1]/"config/thresholds.yaml").read_text())
    assert classify_phase(55, 40, .1, 45, 1.1, cfg, minimum_met=True, confidence=80)=="MID_BULL"
