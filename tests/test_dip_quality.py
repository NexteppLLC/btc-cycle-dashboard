from scoring.metals import calculate_metals_scores
from test_metals_scoring import CFG
def test_dip_only_during_decline_and_bad_dip_cap():
    good=calculate_metals_scores({"mm_trend_score":50,"mm_percentile":40,"drawdown":-.1,"above_200dma":True},CFG,"gold")
    bad=calculate_metals_scores({"mm_trend_score":50,"mm_percentile":40,"drawdown":-.1,"above_200dma":False,"mm_change":-1,"etf_change":-1,"oi_change":1},CFG,"gold")
    assert good.dip_quality==100 and bad.dip_quality<=25
