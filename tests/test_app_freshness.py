"""Exercise current-status UI/report behavior against persisted stale inputs."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from collectors.base import MetricPoint, MetricStatus
from config.settings import get_settings
from database.repository import Repository
from database.session import create_schema, session_scope
from services.health_service import build_diagnostics
from services.report_service import report_text


@pytest.fixture
def freshness_database(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'freshness.db'}")
    get_settings.cache_clear()
    st.cache_data.clear()
    create_schema()
    yield
    st.cache_data.clear()
    get_settings.cache_clear()


def point(name, value, day):
    stamp = datetime.combine(day, datetime.min.time(), timezone.utc)
    return MetricPoint(metric_name=name, timestamp=stamp, value=value, source="measured fixture",
                       fetched_at=datetime.now(timezone.utc), status=MetricStatus.OK,
                       metadata={"effective_date": day.isoformat(), "price_type": "SPOT"})


def seed_recent_btc_with_expired_cohorts():
    today = datetime.now(timezone.utc).date()
    points = [point("btc_price_usd", 77000 + 100*i, today-timedelta(days=30-i)) for i in range(31)]
    points += [point(name, value, today-timedelta(days=4)) for name, value in {
        "lth_mvrv": 3.7, "sth_mvrv": 1.3, "mvrv_zscore": 3.2, "lth_sopr": 1.4,
    }.items()]
    with session_scope() as session:
        repo = Repository(session)
        repo.upsert_metrics(points)
        # These observations were within their age limit at the saved date.
        repo.upsert_snapshot({"date": today-timedelta(days=1), "btc_price": 79900,
                              "lth_mvrv": 3.7, "sth_mvrv": 1.3, "mvrv_zscore": 3.2,
                              "lth_distribution": 74, "cycle_score": 55, "top_risk_score": 20,
                              "cycle_phase": "MID_BULL", "confidence": 90})


def run_app():
    return AppTest.from_file(str(Path(__file__).parents[1] / "app.py")).run(timeout=30)


def metric(tab, label):
    return next(m for m in tab.metric if m.label == label)


def assert_reference_metric(tab, label):
    matches = [m for m in tab.metric if m.label.startswith(label)]
    assert matches and all("参考値" in f"{m.label} {m.value}" for m in matches)


def test_recent_high_confidence_btc_is_partial_everywhere_when_cohorts_expire(freshness_database):
    seed_recent_btc_with_expired_cohorts()
    at = run_app()
    assert not at.exception
    overview, bitcoin, compare, history = at.tabs[0], at.tabs[1], at.tabs[4], at.tabs[5]
    assert metric(overview, "現在").value == "判定保留 / PARTIAL"
    assert metric(bitcoin, "Phase").value == "判定保留 / PARTIAL"
    assert compare.dataframe[0].value.set_index("asset").loc["BTC", "phase"] == "判定保留 / PARTIAL"
    assert metric(bitcoin, "Price").value == "80000.0"  # Fresh price alone is insufficient.
    for label in ("LTH-MVRV", "STH-MVRV", "MVRV Z-Score", "LTH Distribution"):
        assert metric(bitcoin, label).value == "取得不可"
    for tab in (overview, bitcoin):
        for label in ("Cycle Score", "Top Risk"):
            assert_reference_metric(tab, label)
    # The stored phase remains inspectable as history, not overwritten by rendering.
    assert "MID_BULL" in history.dataframe[0].value["cycle_phase"].tolist()
    with session_scope() as session:
        repo = Repository(session)
        quality = build_diagnostics(repo.metrics(), [], [])
        text = report_text(repo.snapshots()[-1], diagnostics=quality)
    assert "フェーズ：判定保留 / PARTIAL" in text
    assert "Cycle Score（参考値）" in text and "Top Risk（参考値）" in text


def test_recent_metal_snapshot_with_expired_cot_has_same_hold_in_ui_and_report(freshness_database):
    seed_recent_btc_with_expired_cohorts()
    today = datetime.now(timezone.utc).date()
    with session_scope() as session:
        repo = Repository(session)
        repo.upsert_metrics([point("gold_price_usd", 2500, today)])
        repo.upsert_cot([{"asset": "GOLD", "report_date": today-timedelta(days=14),
                         "category": "managed_money", "long": 120, "short": 50,
                         "net": 70, "open_interest": 1000, "status": "OK",
                         "source": "CFTC fixture", "fetched_at": datetime.now(timezone.utc)}])
        repo.upsert_metal_snapshot({"asset": "GOLD", "date": today-timedelta(days=1),
                                   "price": 2490, "demand_score": 70, "top_risk_score": 20,
                                   "dip_quality_score": 60, "phase": "MID_BULL", "confidence": 90,
                                   "divergence": "NONE"})
    at = run_app()
    assert not at.exception
    gold, compare = at.tabs[2], at.tabs[4]
    assert metric(gold, "Phase").value == "判定保留 / PARTIAL"
    assert compare.dataframe[0].value.set_index("asset").loc["GOLD", "phase"] == "判定保留 / PARTIAL"
    for label in ("Institutional Demand", "Top Risk", "Dip Quality"):
        assert_reference_metric(gold, label)
    assert any("**Demand State:** 判定保留 / 参考値" in item.value for item in gold.markdown)
    with session_scope() as session:
        repo = Repository(session)
        quality = build_diagnostics(repo.metrics(), repo.cot("gold"), [])
        text = report_text(repo.snapshots()[-1], metals=repo.metal_snapshots(), diagnostics=quality)
    gold_report = text.split("## Gold")[1]
    assert "フェーズ：判定保留 / PARTIAL" in gold_report
    for label in ("Institutional Demand", "Top Risk", "Dip Quality"):
        assert f"{label}（参考値）" in gold_report
