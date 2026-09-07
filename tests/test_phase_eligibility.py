"""Saved confidence cannot override stale current inputs in UI/report phases."""
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from services.phase_service import phase_status
from services.report_service import report_text


TODAY = date(2026, 9, 7)


def diagnostics(asset="btc", *, minimum_met=True, confidence=90, cot="OK"):
    return {"as_of": str(TODAY), "status": "degraded", "sources": {
        f"{asset}_price_usd": {"status": "OK"},
        f"{asset}_cot": {"status": cot},
    }, "phase_eligibility": {asset: {"minimum_met": minimum_met, "confidence": confidence}}}


def snapshot():
    missing = dict.fromkeys(["btc_price", "mvrv_zscore", "lth_mvrv", "sth_mvrv",
                             "lth_distribution", "etf_flow_1d", "etf_flow_7d"])
    return SimpleNamespace(**missing, date=TODAY, cycle_phase="MID_BULL", confidence=90,
                           cycle_score=50, top_risk_score=10, global_mvrv=1.32)


def test_recent_snapshot_holds_when_underlying_onchain_inputs_have_expired():
    quality = diagnostics(minimum_met=False, confidence=25)
    status = phase_status("MID_BULL", 90, TODAY-timedelta(days=1), diagnostics=quality)
    assert status.partial and not status.stale
    assert "insufficient_current_inputs" in status.reasons
    text = report_text(snapshot(), diagnostics=quality)
    assert f"フェーズ：{status.label}" in text
    assert "Top Risk（参考値）" in text
    assert "BTCの現在フェーズはMID_BULL" not in text


def test_current_low_coverage_holds_even_if_minimum_metric_count_passes():
    status = phase_status("MID_BULL", 90, TODAY, diagnostics=diagnostics(confidence=40))
    assert status.partial and "insufficient_current_confidence" in status.reasons


def test_metals_report_and_dashboard_share_cot_freshness_rule():
    quality = diagnostics("gold", cot="UNAVAILABLE_OR_STALE")
    metal = SimpleNamespace(asset="GOLD", date=TODAY, phase="MID_BULL", confidence=90,
                            price=2400, demand_score=70, top_risk_score=20, dip_quality_score=60)
    status = phase_status(metal.phase, metal.confidence, metal.date, metal.asset, diagnostics=quality)
    assert status.partial
    text = report_text(snapshot(), metals=[metal], diagnostics=quality).split("## Gold")[1]
    assert f"フェーズ：{status.label}" in text
    assert "Institutional Demand（参考値）" in text
    assert "Top Risk（参考値）" in text


@pytest.mark.parametrize("day", [None, TODAY+timedelta(days=1), TODAY-timedelta(days=4)])
def test_missing_future_or_stale_snapshot_never_claims_current_phase(day):
    assert phase_status("MID_BULL", 90, day, diagnostics=diagnostics()).partial


@pytest.mark.parametrize("confidence", [None, float("nan"), float("inf"), 49])
def test_unavailable_or_low_saved_confidence_never_passes(confidence):
    assert phase_status("MID_BULL", confidence, TODAY, diagnostics=diagnostics()).partial


def test_fresh_complete_inputs_preserve_formal_phase():
    status = phase_status("MID_BULL", 90, TODAY, diagnostics=diagnostics())
    assert not status.partial and not status.reasons
    assert status.label == "MID_BULL / 上昇中期"


def test_metals_support_current_eligibility_without_recomputed_confidence():
    quality = diagnostics("gold")
    quality["phase_eligibility"]["gold"] = {"minimum_met": True}
    assert not phase_status("MID_BULL", 90, TODAY, "gold", diagnostics=quality).partial


def test_configured_phase_confidence_applies_to_saved_and_current_coverage():
    quality = diagnostics(confidence=90)
    quality["phase_eligibility"]["btc"]["minimum_confidence"] = 60
    assert phase_status("MID_BULL", 55, TODAY, diagnostics=quality).partial
    quality["phase_eligibility"]["btc"]["confidence"] = 55
    assert phase_status("MID_BULL", 90, TODAY, diagnostics=quality).partial
