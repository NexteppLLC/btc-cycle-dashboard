from datetime import date, timedelta
from types import SimpleNamespace

from services.health_service import build_diagnostics
from services.report_service import report_text


TODAY = date(2026, 9, 7)


def price(asset, age=0):
    return dict(metric_name=f"{asset}_price_usd", value=100, status="OK", source="official",
                date=TODAY - timedelta(days=age), fetched_at="2026-09-07", price_type="SPOT")


def test_paid_data_absence_does_not_fail_update():
    result = build_diagnostics([price(a) for a in ("btc", "gold", "silver")], [], [], as_of=TODAY)
    assert result["status"] == "degraded"
    assert result["essential_failures"] == []
    assert result["sources"]["GLD"]["status"] == "UNAVAILABLE_OR_STALE"


def test_stale_prices_fail_even_with_new_download_time():
    result = build_diagnostics([price(a, 30) for a in ("btc", "gold", "silver")], [], [], as_of=TODAY)
    assert result["status"] == "error"
    assert len(result["essential_failures"]) == 3


def test_undated_etf_is_not_marked_healthy():
    result = build_diagnostics([], [], [dict(fund="GLD", status="OK", effective_date=None)], as_of=TODAY)
    assert result["sources"]["GLD"]["status"] == "UNAVAILABLE_OR_STALE"


def test_report_marks_partial_scores_and_includes_free_mvrv():
    fields = dict.fromkeys(["btc_price", "mvrv_zscore", "lth_mvrv", "sth_mvrv", "lth_distribution",
                           "etf_flow_1d", "etf_flow_7d"])
    snapshot = SimpleNamespace(**fields, date=TODAY, cycle_phase="PARTIAL", confidence=25,
                               cycle_score=50, top_risk_score=0, global_mvrv=1.32)
    text = report_text(snapshot)
    assert "Global MVRV：1.32" in text
    assert "Top Risk（参考値）" in text
    assert "判定保留" in text
    assert "nan" not in text


def test_old_high_confidence_report_does_not_claim_current_market_phase():
    fields = dict.fromkeys(["btc_price", "mvrv_zscore", "lth_mvrv", "sth_mvrv", "lth_distribution",
                           "etf_flow_1d", "etf_flow_7d"])
    snapshot = SimpleNamespace(**fields, date=date(2020, 1, 1), cycle_phase="MID_BULL", confidence=90,
                               cycle_score=50, top_risk_score=10, global_mvrv=1.32)
    text = report_text(snapshot)
    assert "判定保留 / PARTIAL" in text
    assert "期限切れ" in text
    assert "BTCの現在フェーズはMID_BULL" not in text
