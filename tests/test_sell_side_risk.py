import numpy as np
import pandas as pd
import pytest

from indicators.btc_core import sell_side_risk_series


def series(values, start="2026-01-01"):
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq="D", tz="UTC"), dtype=float)


def test_sell_side_risk_uses_official_15_day_sma_formula():
    result = sell_side_risk_series(series([8] * 15), series([2] * 15), series([1000] * 15))
    assert result.iloc[:14].isna().all()
    assert result.iloc[-1] == pytest.approx(0.01)


def test_sell_side_risk_requires_fifteen_consecutive_aligned_days():
    profit = series([8] * 15)
    loss = series([2] * 15)
    loss.iloc[7] = np.nan
    result = sell_side_risk_series(profit, loss, series([1000] * 15))
    assert result.dropna().empty


def test_sell_side_risk_rejects_misaligned_current_dates():
    profit = series([8] * 15)
    loss = series([2] * 15, start="2026-01-02")
    cap = series([1000] * 15)
    assert sell_side_risk_series(profit, loss, cap).dropna().empty


@pytest.mark.parametrize("field,bad", [
    ("profit", np.nan),
    ("profit", np.inf),
    ("profit", -1),
    ("loss", -1),
    ("cap", 0),
    ("cap", np.inf),
])
def test_sell_side_risk_invalid_input_blocks_the_window(field, bad):
    inputs = {"profit": series([8] * 15), "loss": series([2] * 15), "cap": series([1000] * 15)}
    inputs[field].iloc[-1] = bad
    result = sell_side_risk_series(inputs["profit"], inputs["loss"], inputs["cap"])
    assert result.iloc[-1] is np.nan or pd.isna(result.iloc[-1])


def test_sell_side_risk_with_less_than_fifteen_days_is_unavailable():
    result = sell_side_risk_series(series([8] * 14), series([2] * 14), series([1000] * 14))
    assert result.dropna().empty


def test_sell_side_risk_rejects_invalid_window():
    with pytest.raises(ValueError):
        sell_side_risk_series(series([1]), series([1]), series([1]), window=0)
