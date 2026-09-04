from scoring.metals import detect_divergence
def test_bearish_and_bullish_divergence():
    assert detect_divergence(1,-1,None,None,None)=="BEARISH"
    assert detect_divergence(-1,None,1,None,None)=="BULLISH"
