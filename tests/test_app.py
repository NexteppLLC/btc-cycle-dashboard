"""Execute all Streamlit tabs against isolated empty and populated databases."""
from datetime import datetime, timezone
from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from config.settings import get_settings
from database.repository import Repository
from database.session import create_schema, session_scope


@pytest.fixture
def app_database(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'app.db'}")
    get_settings.cache_clear()
    st.cache_data.clear()
    create_schema()
    yield
    st.cache_data.clear()
    get_settings.cache_clear()


def run_app():
    return AppTest.from_file(str(Path(__file__).parents[1] / "app.py")).run(timeout=30)


def test_empty_database_has_working_update_controls(app_database):
    at = run_app()
    assert not at.exception
    assert len(at.tabs) == 7
    assert at.button(key="reload_data").label == "最新の保存データを表示"
    assert at.button(key="collect_data").label == "データを取得・更新"
    at.button(key="reload_data").click().run(timeout=30)
    assert not at.exception


def test_all_holder_and_score_cards_are_visible(app_database):
    today = datetime.now(timezone.utc).date()
    with session_scope() as session:
        Repository(session).upsert_snapshot({"date": today, "btc_price": 80000,
                                           "cycle_score": 50, "top_risk_score": 10,
                                           "cycle_phase": "PARTIAL", "confidence": 15})
    at = run_app()
    assert not at.exception
    labels = [m.label for m in at.metric]
    # Regression: zip(st.columns(4), eight_items) silently hid the second row.
    for label in ("Phase", "Confidence", "lth_supply", "sth_supply", "cdd"):
        assert label in labels
    assert [m.value for m in at.metric if m.label == "cdd"] == ["取得不可"]
    compare = [df.value for df in at.dataframe if "asset" in df.value.columns]
    assert any("BTC" in frame["asset"].tolist() for frame in compare)
