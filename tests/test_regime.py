import yaml
from pathlib import Path
from scoring.regime import calculate_confidence, classify_phase
CFG=yaml.safe_load((Path(__file__).parents[1]/"config/thresholds.yaml").read_text())
def test_phase_uses_multiple_signals():
    assert classify_phase(75,40,.2,50,1.2,CFG)=="LATE_BULL"
    assert classify_phase(60,20,-.1,20,.9,CFG)=="BEAR"
def test_confidence_penalties():
    full=calculate_confidence(coverage=1,glassnode=True,etf_current=True,config=CFG)
    degraded=calculate_confidence(coverage=.5,glassnode=False,etf_current=False,history_sufficient=False,config=CFG)
    assert full==100 and degraded < 50

