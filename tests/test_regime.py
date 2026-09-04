import yaml
from pathlib import Path
from scoring.regime import btc_minimum_data, calculate_confidence, classify_phase, weighted_confidence
CFG=yaml.safe_load((Path(__file__).parents[1]/"config/thresholds.yaml").read_text())
def test_phase_uses_multiple_signals():
    assert classify_phase(75,40,.2,50,1.2,CFG)=="LATE_BULL"
    assert classify_phase(60,20,-.1,20,.9,CFG)=="BEAR"
def test_confidence_penalties():
    full=calculate_confidence(coverage=1,glassnode=True,etf_current=True,config=CFG)
    degraded=calculate_confidence(coverage=.5,glassnode=False,etf_current=False,history_sufficient=False,config=CFG)
    assert full==100 and degraded < 50

def test_btc_price_only_holds_phase():
    values={"btc_price_usd":90000,"btc_trend":.1}
    met, missing=btc_minimum_data(values)
    confidence=weighted_confidence({"price":True,"trend":True},CFG["confidence_weights"]["btc"])
    assert not met and missing and confidence < 50
    assert classify_phase(64,20,.1,None,None,CFG,minimum_met=met,confidence=confidence)=="PARTIAL"

def test_full_btc_data_allows_normal_phase():
    values={"btc_price_usd":90000,"btc_trend":.1,"lth_mvrv":2,"sth_mvrv":1.2}
    met,_=btc_minimum_data(values)
    assert met
    assert classify_phase(64,20,.1,20,1.2,CFG,minimum_met=met,confidence=80)=="MID_BULL"

def test_missing_etf_reduces_decision_confidence():
    weights=CFG["confidence_weights"]["btc"]
    full=weighted_confidence({k:True for k in weights},weights)
    missing=weighted_confidence({k:k!="etf" for k in weights},weights)
    assert full==100 and missing==95
