import yaml
from pathlib import Path
from indicators.holders import distribution_score
from scoring.cycle_score import calculate_cycle_score
from scoring.top_risk import calculate_top_risk

CFG=yaml.safe_load((Path(__file__).parents[1]/"config/thresholds.yaml").read_text())
def test_cycle_score_and_explanation():
    r=calculate_cycle_score({"lth_mvrv":2.5,"sth_mvrv":1.3,"lth_distribution":50,"etf_flow":0,"mvrv_zscore":3.5,"btc_trend":.125},CFG["cycle"])
    assert r.score == 50 and len(r.details)==6 and round(sum(x["contribution"] for x in r.details),2)==50
def test_missing_reweights_not_zero():
    r=calculate_cycle_score({"lth_mvrv":2.5},CFG["cycle"]); assert r.score==50 and r.coverage==.25
def test_top_risk_bounds():
    r=calculate_top_risk({"lth_mvrv":5,"mvrv_zscore":8,"lth_distribution":100},CFG["top_risk"]); assert r.score==100
def test_distribution_missing(): assert distribution_score({}) == (None, 0.0)

