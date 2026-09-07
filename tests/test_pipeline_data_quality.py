from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pandas as pd
import pytest
from sqlalchemy import select

from database.models import ScoringDetail
from database.repository import Repository
from database.session import create_schema, session_scope
from scoring.metals import calculate_metals_scores, position_statistics
from services.data_quality import current_metric_row, metric_current, metric_series
from services.update_service import build_btc_inputs, build_metal_inputs, etf_holdings_change, load_thresholds


TODAY = date(2026, 9, 7)


def metric(name, value, day=TODAY, source="measured", status="OK", **kwargs):
    return {"metric_name": name, "value": value, "date": day, "effective_date": day,
            "timestamp": datetime.combine(day, datetime.min.time(), timezone.utc),
            "fetched_at": datetime(2026, 9, 7, tzinfo=timezone.utc), "source": source,
            "status": status, **kwargs}


def test_current_inputs_use_effective_dates_and_status_not_download_recency():
    old = metric("lth_mvrv", 4, day=TODAY - timedelta(days=60))
    assert metric_current([old], "lth_mvrv", TODAY) is None
    assert metric_current([metric("lth_mvrv", 4, status="STALE")], "lth_mvrv", TODAY) is None
    assert metric_current([metric("lth_mvrv", float("nan"))], "lth_mvrv", TODAY) is None
    assert metric_current([metric("lth_mvrv", float("inf"))], "lth_mvrv", TODAY) is None
    assert metric_current([metric("lth_mvrv", 2, day=TODAY + timedelta(days=1))], "lth_mvrv", TODAY) is None
    assert metric_current([metric("etf_flow_usd", 0)], "etf_flow_usd", TODAY) == 0


def test_new_missing_observation_does_not_resurrect_earlier_same_source_value():
    rows = [metric("lth_mvrv", 4, day=TODAY - timedelta(days=1)), metric("lth_mvrv", None, status="MISSING")]
    assert metric_current(rows, "lth_mvrv", TODAY) is None
    assert pd.isna(metric_series(rows, "lth_mvrv", TODAY).iloc[-1])


def test_failed_primary_allows_current_fallback_and_never_accepts_zero_price():
    rows = [metric("btc_price_usd", 100, day=TODAY-timedelta(days=1), source="primary"),
            metric("btc_price_usd", None, source="primary", status="ERROR"),
            metric("btc_price_usd", 101, day=TODAY-timedelta(days=1), source="fallback")]
    assert metric_current(rows, "btc_price_usd", TODAY) == 101
    assert list(metric_series(rows, "btc_price_usd", TODAY)) == [101]
    assert metric_current([metric("btc_price_usd", 0)], "btc_price_usd", TODAY) is None


def test_price_current_and_history_use_same_source_without_splicing_proxy_units():
    rows = [metric("gold_price_usd", 2400 + i, TODAY - timedelta(days=40-i), source="spot", price_type="SPOT") for i in range(40)]
    rows += [metric("gold_price_usd", 250, source="GLD", price_type="ETF_PROXY")]
    selected = metric_series(rows, "gold_price_usd", TODAY)
    assert list(selected) == [250]
    assert current_metric_row(rows, "gold_price_usd", TODAY)["source"] == "GLD"
    values = build_metal_inputs(rows, [], [], "gold", TODAY)
    assert values["price"] == 250
    assert values["trend_score"] is None and values["above_200dma"] is None


def test_equal_date_metal_futures_are_preferred_to_etf_share_price():
    rows = [metric("gold_price_usd", 2500, source="GC=F", price_type="FUTURES_PROXY"),
            metric("gold_price_usd", 250, source="GLD", price_type="ETF_PROXY")]
    assert metric_current(rows, "gold_price_usd", TODAY) == 2500


def test_btc_duplicate_providers_do_not_change_trend_or_current_price():
    rows = [metric("btc_price_usd", 100 + i, TODAY - timedelta(days=30-i), source="spot") for i in range(31)]
    rows += [metric("btc_price_usd", 50000, TODAY - timedelta(days=30-i), source="alternate") for i in range(31)]
    series = metric_series(rows, "btc_price_usd", TODAY)
    values, _, _ = build_btc_inputs(rows, TODAY)
    assert len(series) == 31 and values["btc_price_usd"] == series.iloc[-1]
    assert values["btc_trend"] == pytest.approx(series.iloc[-1] / series.iloc[0] - 1)
    assert values["trend_deviation"] is None


def test_btc_missing_daily_price_is_not_compressed_into_30_day_return():
    rows = [metric("btc_price_usd", 100 + i, TODAY - timedelta(days=31-i)) for i in range(32) if i != 1]
    values, _, _ = build_btc_inputs(rows, TODAY)
    assert values["btc_trend"] is None


def test_onchain_mvrv_is_not_derived_from_independently_dated_caps():
    rows = [metric("market_cap_usd", 1000), metric("realized_cap_usd", 500, TODAY - timedelta(days=1))]
    values, _, _ = build_btc_inputs(rows, TODAY)
    assert values["global_mvrv"] is None


def test_stale_btc_history_and_global_cdd_do_not_supply_current_cohort_signals():
    rows = [metric("lth_mvrv", 4, TODAY - timedelta(days=60))]
    rows += [metric("cdd", 100 + i, TODAY - timedelta(days=40-i)) for i in range(41)]
    values, _, coverage = build_btc_inputs(rows, TODAY)
    assert values["lth_mvrv"] is None
    assert values["lth_distribution"] is None and coverage == 0


def holding(day, *, source="sponsor", **values):
    return {"fund": "GLD", "status": "OK", "source": source, "date": day, "effective_date": day, **values}


def test_etf_nav_only_and_undated_or_stale_snapshots_never_become_flow_signals():
    rows = [holding(TODAY-timedelta(days=1), nav=100, net_assets=100), holding(TODAY, nav=110, net_assets=110)]
    assert etf_holdings_change(rows, TODAY) is None
    assert etf_holdings_change([holding(None, ounces=100), holding(TODAY, ounces=110)], TODAY) is None
    assert etf_holdings_change([holding(TODAY-timedelta(days=9), ounces=100), holding(TODAY-timedelta(days=8), ounces=110)], TODAY) is None
    assert etf_holdings_change([holding(TODAY-timedelta(days=60), ounces=100), holding(TODAY, ounces=110)], TODAY) is None


def test_etf_measured_holdings_changes_preserve_zero_and_require_comparable_units():
    rows = [holding(TODAY-timedelta(days=1), ounces=100, nav=100), holding(TODAY, ounces=100, nav=110)]
    assert etf_holdings_change(rows, TODAY) == 0
    rows[-1]["ounces"] = 110
    assert etf_holdings_change(rows, TODAY) == pytest.approx(.1)
    assert etf_holdings_change([holding(TODAY-timedelta(days=1), physical_holdings=100, holdings_unit="OUNCES"),
                               holding(TODAY, physical_holdings=110, holdings_unit="TONNES")], TODAY) is None


def test_empty_metals_inputs_have_no_fabricated_scores_or_divergence():
    values = build_metal_inputs([], [], [], "gold", TODAY)
    for key in ("mm_trend_score", "oi_score", "commercial_score", "position_reset", "oi_reset", "reaccumulation", "trend_score"):
        assert values[key] is None
    scores = calculate_metals_scores(values, load_thresholds()["metals"], "gold")
    assert scores.demand is None and scores.top_risk is None and scores.dip_quality is None
    assert scores.confidence == 0 and scores.phase == "PARTIAL" and scores.divergence == "UNKNOWN"


def test_stale_cot_is_not_current_demand_and_blocks_classification():
    cot = [{"category": "managed_money", "status": "OK", "report_date": TODAY-timedelta(weeks=30-i),
            "net": 100+i, "long": 200+i, "short": 100, "open_interest": 1000+i} for i in range(25)]
    values = build_metal_inputs([metric("gold_price_usd", 2500)], cot, [], "gold", TODAY)
    assert values["cot_stale"] and values["mm_percentile"] is None and values["mm_trend_score"] is None
    scores = calculate_metals_scores(values, load_thresholds()["metals"], "gold")
    assert scores.phase == "PARTIAL" and scores.confidence == 20


def test_new_missing_cot_does_not_reuse_previous_report_as_current():
    cot = [{"category": "managed_money", "status": "OK", "report_date": TODAY-timedelta(weeks=25-i),
            "net": 100+i, "long": 200+i, "short": 100, "open_interest": 1000+i} for i in range(25)]
    cot.append({**cot[-1], "report_date": TODAY, "status": "MISSING"})
    values = build_metal_inputs([], cot, [], "gold", TODAY)
    assert values["mm_percentile"] is None and values["open_interest"] is None


def test_cot_changes_require_actual_weekly_report_interval():
    rows = [{"report_date": TODAY-timedelta(weeks=2), "net": 1, "open_interest": 100},
            {"report_date": TODAY, "net": 3, "open_interest": 120}]
    stats = position_statistics(rows)
    assert stats["change_1w"] is None and stats["oi_change_1w"] is None


def test_cot_52_week_percentile_does_not_relabel_sparse_multiyear_history():
    rows = [{"report_date": TODAY-timedelta(weeks=4*i), "net": i, "open_interest": 100} for i in range(52)]
    stats = position_statistics(rows)
    assert stats["percentile_52w"] is None  # only thirteen reports in the actual year
    assert stats["percentile_full"] is not None


def test_replacing_score_details_removes_components_that_are_now_missing(tmp_path):
    url = f"sqlite:///{tmp_path / 'scores.db'}"
    create_schema(url)
    detail = {"component": "lth_mvrv", "raw_value": 2, "normalized_score": 50, "weight": 1, "contribution": 50, "reason": "measured"}
    with session_scope(url) as session:
        repo = Repository(session)
        repo.replace_scoring_details(TODAY, [detail])
        session.flush()
        repo.replace_scoring_details(TODAY, [])
    with session_scope(url) as session:
        assert list(session.scalars(select(ScoringDetail))) == []


def test_entire_update_with_collectors_unavailable_persists_missing_safe_snapshots(monkeypatch, tmp_path):
    import services.update_service as service
    url = f"sqlite:///{tmp_path / 'update.db'}"
    class EmptyCollector:
        def __init__(self, *args, **kwargs):
            self.diagnostics = {}
        def fetch_history(self, *args):
            return []
    for name in ("BTCPriceCollector", "OnChainCollector", "GlassnodeCollector", "ETFFlowCollector", "MetalsPriceCollector", "MetalsETFCollector", "CFTCCollector"):
        monkeypatch.setattr(service, name, EmptyCollector)
    monkeypatch.setattr(service, "get_settings", lambda: SimpleNamespace(http_timeout_seconds=1, glassnode_api_key=None, etf_flow_csv_url=None))
    monkeypatch.setattr(service, "create_schema", lambda: create_schema(url))
    monkeypatch.setattr(service, "session_scope", lambda: session_scope(url))
    result = service.run_update(days=30)
    assert result["snapshot"].cycle_phase == "PARTIAL"
    assert result["snapshot"].cycle_score is None and result["snapshot"].top_risk_score is None
    for metal in result["metals"]:
        assert metal.phase == "PARTIAL" and metal.confidence == 0
        assert metal.demand_score is None and metal.top_risk_score is None
    # Same-day reruns must update rows, including clearing previously available details.
    service.run_update(days=30)
    with session_scope(url) as session:
        assert len(Repository(session).snapshots()) == 1
        assert len(Repository(session).metal_snapshots()) == 2
