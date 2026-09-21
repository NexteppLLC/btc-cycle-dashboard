from datetime import date, datetime, timedelta, timezone

import pandas as pd
import pytest

from indicators.btc_core import build_core5
from scoring.regime import detect_core5_alerts
from services.update_service import build_btc_core5, load_thresholds


CFG = load_thresholds()
CORE_CFG = CFG["btc_core5"]
TODAY = date(2026, 9, 21)


def daily(value, days=400):
    return pd.Series([value] * days, index=pd.date_range(end=TODAY, periods=days, freq="D"))


def core(sth_mvrv=1.13, sth_sopr=1.02, lth_mvrv=1.65, distribution=28, risk=.0008):
    values = {
        "sth_mvrv": sth_mvrv,
        "sth_sopr": sth_sopr,
        "lth_mvrv": lth_mvrv,
        "lth_distribution": distribution,
        "sell_side_risk": risk,
    }
    history = {name: daily(value) if value is not None else pd.Series(dtype=float)
               for name, value in values.items()}
    dates = {name: TODAY if value is not None else None for name, value in values.items()}
    return build_core5(history, values, dates, CORE_CFG)


def test_healthy_core5_state_and_layers():
    result = core()
    assert result["state"] == "HEALTHY BULL"
    assert result["short_term_health"] == "HEALTHY"
    assert result["cycle_heat"] == "NORMAL"
    assert result["distribution_pressure"] == "LOW"
    assert result["cards"]["sell_side_risk"]["status"] == "COMPRESSION"
    assert result["streaks"]["sth_recovery_days"] == 400


@pytest.mark.parametrize("kwargs,state", [
    ({"sth_mvrv": .9, "sth_sopr": .95}, "STRESS"),
    ({"lth_mvrv": 3.5}, "OVERHEATED"),
    ({"lth_mvrv": 3.5, "distribution": 70}, "DISTRIBUTION RISK"),
    ({"risk": .0075}, "OVERHEATED"),
    ({"risk": None}, "RECOVERY"),
    ({"sth_sopr": None, "risk": None}, "PARTIAL"),
])
def test_core5_final_state_precedence(kwargs, state):
    assert core(**kwargs)["state"] == state


def test_core5_alert_thresholds_and_two_day_confirmation():
    values = {
        "sth_stress_days": 2,
        "sth_recovery_days": 0,
        "lth_mvrv": 3.6,
        "lth_distribution": 82,
        "sell_side_risk": .008,
        "sell_side_percentile_4y": .96,
        "btc5_state": "DISTRIBUTION RISK",
    }
    alerts = detect_core5_alerts(values, CFG)
    for expected in (
        "BTC5_STH_STRESS", "BTC5_LTH_HEAT_HIGH", "BTC5_LTH_DISTRIBUTION_HIGH",
        "BTC5_LTH_DISTRIBUTION_EXTREME", "BTC5_SELL_SIDE_HIGH",
        "BTC5_SELL_SIDE_EXTREME", "BTC5_DISTRIBUTION_RISK",
    ):
        assert expected in alerts


def row(name, value, day, source="Glassnode API v1", status="OK"):
    stamp = datetime.combine(day, datetime.min.time(), timezone.utc)
    return {"metric_name": name, "value": value, "date": day, "effective_date": day,
            "timestamp": stamp, "fetched_at": stamp + timedelta(hours=1),
            "source": source, "status": status}


def glassnode_rows(days=400):
    rows = []
    for offset in range(days):
        day = TODAY - timedelta(days=days - offset - 1)
        rows += [row("sth_mvrv", 1.13, day), row("sth_sopr", 1.02, day),
                 row("lth_mvrv", 1.65, day), row("realized_profit", 80, day),
                 row("realized_loss", 20, day), row("glassnode_realized_cap_usd", 100000, day)]
    return rows


def test_service_builds_sell_side_risk_from_glassnode_only():
    rows = glassnode_rows()
    # A same-named free-provider cap must never enter the calculation.
    rows.append(row("realized_cap_usd", 1, TODAY, source="Coin Metrics Community API v4"))
    result = build_btc_core5(rows, TODAY, 28, pd.Series({TODAY: 28}), CFG)
    assert result["cards"]["sell_side_risk"]["current"] == pytest.approx(.001)
    assert result["cards"]["sell_side_risk"]["observation_date"] == TODAY
    assert result["state"] == "HEALTHY BULL"
    assert "BTC5_SELL_SIDE_COMPRESSION" in result["alerts"]


def test_service_rejects_mismatched_current_input_dates():
    rows = glassnode_rows(15)
    rows = [item for item in rows if not (item["metric_name"] == "realized_loss" and item["date"] == TODAY)]
    result = build_btc_core5(rows, TODAY, 28, cfg=CFG)
    assert result["cards"]["sell_side_risk"]["current"] is None
    assert result["cards"]["sell_side_risk"]["status"] == "UNAVAILABLE"


def test_service_rejects_mixed_current_input_providers():
    rows = glassnode_rows(15)
    for item in rows:
        if item["metric_name"] == "realized_loss":
            item["source"] = "alternate provider"
    result = build_btc_core5(rows, TODAY, 28, cfg=CFG)
    assert result["cards"]["sell_side_risk"]["current"] is None
