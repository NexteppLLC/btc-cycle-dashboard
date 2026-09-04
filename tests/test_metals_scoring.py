from scoring.metals import calculate_metals_scores, percentile, position_statistics

CFG={"gold":{"demand_weights":{"mm_trend":1},"risk_weights":{"mm_net":1},"dip_weights":{"drawdown":1},"dip_min":.05,"dip_max":.15,"phase":{"early_bull":35,"mid_bull":55,"late_bull":75,"top_risk":80}}}
def test_statistics_and_missing_history():
    rows=[{"report_date":i,"net":float(i),"long":i+10,"short":10,"open_interest":100} for i in range(1,54)]
    stats=position_statistics(rows)
    assert stats["change_13w"]==13 and stats["net_oi"]==.53 and stats["percentile_52w"]==100
    assert percentile([1,2],2) is None
def test_demand_phase():
    score=calculate_metals_scores({"mm_trend_score":80,"mm_percentile":60,"drawdown":None,"above_200dma":True},CFG,"gold")
    assert score.demand==80 and score.dip_quality is None and score.phase=="LATE_BULL"
