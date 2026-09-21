"""Pure calculations and classifications for the Bitcoin Core 5 monitor.

The Core 5 layer is deliberately separate from Cycle Score/Phase.  Missing or
misaligned observations remain unavailable; the monitor never fills them with
zeroes or estimates.
"""
from __future__ import annotations

from datetime import date
from typing import Mapping

import numpy as np
import pandas as pd

from .normalization import finite_number


CORE5_METRICS = (
    "sth_mvrv",
    "sth_sopr",
    "lth_mvrv",
    "lth_distribution",
    "sell_side_risk",
)


def _daily_series(series: pd.Series | None) -> pd.Series:
    """Return a sorted UTC-day series with explicit NaNs for calendar gaps."""
    if series is None or len(series) == 0:
        return pd.Series(dtype=float)
    values = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan)
    index = pd.to_datetime(values.index, utc=True, errors="coerce")
    valid = ~index.isna()
    values = pd.Series(values.to_numpy()[valid], index=index[valid], dtype=float)
    if values.empty:
        return values
    values = values.groupby(values.index.normalize()).last().sort_index()
    return values.asfreq("D")


def sell_side_risk_series(
    realized_profit: pd.Series,
    realized_loss: pd.Series,
    realized_cap: pd.Series,
    *,
    window: int = 15,
) -> pd.Series:
    """Calculate Glassnode's 15-day Sell-Side Risk Ratio.

    Formula: SMA((Realized Profit + Realized Loss) / Realized Cap, 15).
    All three inputs must exist on the same observation date.  Invalid values,
    a non-positive cap, or a calendar gap make the affected rolling window NaN.
    """
    if window < 1:
        raise ValueError("window must be positive")
    inputs = {
        "profit": _daily_series(realized_profit),
        "loss": _daily_series(realized_loss),
        "cap": _daily_series(realized_cap),
    }
    non_empty = [series for series in inputs.values() if not series.empty]
    if len(non_empty) != 3:
        return pd.Series(dtype=float, name="sell_side_risk")
    start = min(series.index.min() for series in non_empty)
    end = max(series.index.max() for series in non_empty)
    index = pd.date_range(start, end, freq="D", tz="UTC")
    frame = pd.DataFrame({name: series.reindex(index) for name, series in inputs.items()})
    valid = (
        frame["profit"].ge(0)
        & frame["loss"].ge(0)
        & frame["cap"].gt(0)
        & np.isfinite(frame).all(axis=1)
    )
    raw = ((frame["profit"] + frame["loss"]) / frame["cap"]).where(valid)
    result = raw.rolling(window=window, min_periods=window).mean()
    result.name = "sell_side_risk"
    return result


def _calendar_value(series: pd.Series, observation_date: date | None, days_ago: int) -> float | None:
    if observation_date is None or series.empty:
        return None
    key = pd.Timestamp(observation_date, tz="UTC") - pd.Timedelta(days=days_ago)
    return finite_number(series.get(key))


def _percentile(series: pd.Series, observation_date: date | None, days: int, minimum: int) -> float | None:
    current = _calendar_value(series, observation_date, 0)
    if current is None:
        return None
    end = pd.Timestamp(observation_date, tz="UTC")
    sample = series.loc[(series.index > end - pd.Timedelta(days=days)) & (series.index <= end)].dropna()
    return None if len(sample) < minimum else float((sample <= current).mean())


def metric_card(
    series: pd.Series | None,
    current: object,
    observation_date: date | None,
    *,
    include_4y: bool = False,
) -> dict[str, float | str | date | None]:
    """Build missing-safe card statistics using calendar-day comparisons."""
    values = _daily_series(series)
    current_value = finite_number(current)
    if current_value is None or observation_date is None:
        return {
            "current": None,
            "daily_change": None,
            "change_7d": None,
            "percentile_52w": None,
            "percentile_4y": None,
            "observation_date": None,
            "status": "UNAVAILABLE",
        }
    observed = pd.Timestamp(observation_date, tz="UTC")
    values = values.loc[values.index <= observed]
    if values.empty:
        values = pd.Series([current_value], index=[observed], dtype=float)
    else:
        values.loc[observed] = current_value
        values = values.sort_index().asfreq("D")
    prior, week = _calendar_value(values, observation_date, 1), _calendar_value(values, observation_date, 7)
    return {
        "current": current_value,
        "daily_change": None if prior is None else current_value - prior,
        "change_7d": None if week is None else current_value - week,
        "percentile_52w": _percentile(values, observation_date, 365, 30),
        "percentile_4y": _percentile(values, observation_date, 1461, 365) if include_4y else None,
        "observation_date": observation_date,
        "status": "AVAILABLE",
    }


def _sth_health(sth_mvrv: float | None, sth_sopr: float | None, cfg: Mapping) -> str:
    if sth_mvrv is None or sth_sopr is None:
        return "UNAVAILABLE"
    if sth_mvrv < cfg["mvrv_profit"]:
        return "STRESS"
    if sth_sopr < cfg["sopr_profit"]:
        return "RECOVERY"
    if sth_sopr >= cfg["sopr_profit_taking"]:
        return "PROFIT TAKING"
    if sth_mvrv >= cfg["mvrv_healthy"]:
        return "HEALTHY"
    return "RECOVERY"


def _cycle_heat(lth_mvrv: float | None, cfg: Mapping) -> str:
    if lth_mvrv is None:
        return "UNAVAILABLE"
    if lth_mvrv >= cfg["extreme"]:
        return "EXTREME"
    if lth_mvrv >= cfg["high"]:
        return "HIGH"
    if lth_mvrv >= cfg["normal"]:
        return "NORMAL"
    return "LOW"


def _sell_side_status(card: Mapping, cfg: Mapping) -> str:
    value = finite_number(card.get("current"))
    percentile = finite_number(card.get("percentile_4y"))
    if value is None:
        return "UNAVAILABLE"
    # Absolute reference levels take precedence when percentile and level
    # conflict (for example, a flat low-risk history has a 100th percentile).
    if value <= cfg["low"]:
        return "COMPRESSION"
    if value >= cfg["high"]:
        return "EXTREME" if percentile is not None and percentile >= cfg["percentile_extreme"] else "HIGH REALIZATION"
    if percentile is not None and percentile >= cfg["percentile_extreme"]:
        return "EXTREME"
    if percentile is not None and percentile >= cfg["percentile_high"]:
        return "HIGH REALIZATION"
    if percentile is not None and percentile <= cfg["percentile_low"]:
        return "COMPRESSION"
    return "NORMAL"


def _distribution_pressure(
    distribution: float | None,
    sell_side_status: str,
    cfg: Mapping,
) -> str:
    if distribution is not None and distribution >= cfg["extreme"] or sell_side_status == "EXTREME":
        return "EXTREME"
    if distribution is not None and distribution >= cfg["high"] or sell_side_status == "HIGH REALIZATION":
        return "HIGH"
    if distribution is None or sell_side_status == "UNAVAILABLE":
        return "PARTIAL"
    if distribution >= cfg["rising"]:
        return "RISING"
    return "LOW"


def _core5_state(values: Mapping[str, float | None], sell_status: str, cfg: Mapping) -> str:
    sth_mvrv = finite_number(values.get("sth_mvrv"))
    sth_sopr = finite_number(values.get("sth_sopr"))
    lth_mvrv = finite_number(values.get("lth_mvrv"))
    distribution = finite_number(values.get("lth_distribution"))
    sell_side = finite_number(values.get("sell_side_risk"))
    sell_high = sell_status in {"HIGH REALIZATION", "EXTREME"}
    heat_high = lth_mvrv is not None and lth_mvrv >= cfg["lth_mvrv"]["high"]
    distribution_high = distribution is not None and distribution >= cfg["distribution"]["high"]
    if distribution_high and (heat_high or sell_high):
        return "DISTRIBUTION RISK"
    if heat_high or sell_high:
        return "OVERHEATED"
    if sth_mvrv is not None and sth_sopr is not None and sth_mvrv < 1 and sth_sopr < 1:
        return "STRESS"
    complete = all(value is not None for value in (sth_mvrv, sth_sopr, lth_mvrv, distribution, sell_side))
    if complete and sth_mvrv > 1 and sth_sopr >= 1 and lth_mvrv < cfg["lth_mvrv"]["high"] and distribution < cfg["distribution"]["high"]:
        return "HEALTHY BULL"
    if sth_mvrv is not None and sth_sopr is not None and distribution is not None and sth_mvrv >= 1 and sth_sopr >= 1 and distribution < cfg["distribution"]["high"]:
        return "RECOVERY"
    return "PARTIAL"


def _trailing_days(condition: pd.Series, observation_date: date | None) -> int:
    if observation_date is None or condition.empty:
        return 0
    values = condition.reindex(pd.date_range(condition.index.min(), pd.Timestamp(observation_date, tz="UTC"), freq="D"))
    count = 0
    for value in reversed(values.tolist()):
        if value is not True and not isinstance(value, np.bool_):
            break
        if not bool(value):
            break
        count += 1
    return count


def build_core5(
    series: Mapping[str, pd.Series],
    current: Mapping[str, object],
    observation_dates: Mapping[str, date | None],
    cfg: Mapping,
) -> dict:
    """Build cards, three interpretation layers and a conservative final state."""
    cards = {}
    for name in CORE5_METRICS:
        cards[name] = metric_card(
            series.get(name),
            current.get(name),
            observation_dates.get(name),
            include_4y=name == "sell_side_risk",
        )
    values = {name: finite_number(card["current"]) for name, card in cards.items()}
    cards["sth_mvrv"]["status"] = (
        "STRESS" if values["sth_mvrv"] is not None and values["sth_mvrv"] < 1
        else "PROFIT" if values["sth_mvrv"] is not None
        else "UNAVAILABLE"
    )
    cards["sth_sopr"]["status"] = (
        "LOSS REALIZATION" if values["sth_sopr"] is not None and values["sth_sopr"] < 1
        else "PROFIT REALIZATION" if values["sth_sopr"] is not None
        else "UNAVAILABLE"
    )
    cards["lth_mvrv"]["status"] = _cycle_heat(values["lth_mvrv"], cfg["lth_mvrv"])
    distribution = values["lth_distribution"]
    cards["lth_distribution"]["status"] = (
        "UNAVAILABLE" if distribution is None
        else "EXTREME" if distribution >= cfg["distribution"]["extreme"]
        else "HIGH" if distribution >= cfg["distribution"]["high"]
        else "RISING" if distribution >= cfg["distribution"]["rising"]
        else "LOW"
    )
    sell_status = _sell_side_status(cards["sell_side_risk"], cfg["sell_side_risk"])
    cards["sell_side_risk"]["status"] = sell_status

    sth_mvrv = _daily_series(series.get("sth_mvrv"))
    sth_sopr = _daily_series(series.get("sth_sopr"))
    aligned = pd.concat({"mvrv": sth_mvrv, "sopr": sth_sopr}, axis=1) if not sth_mvrv.empty and not sth_sopr.empty else pd.DataFrame()
    sth_date = observation_dates.get("sth_mvrv") if observation_dates.get("sth_mvrv") == observation_dates.get("sth_sopr") else None
    stress_days = _trailing_days((aligned.mvrv < 1) & (aligned.sopr < 1), sth_date) if not aligned.empty else 0
    recovery_days = _trailing_days((aligned.mvrv >= 1) & (aligned.sopr >= 1), sth_date) if not aligned.empty else 0
    state = _core5_state(values, sell_status, cfg)
    return {
        "cards": cards,
        "short_term_health": _sth_health(values["sth_mvrv"], values["sth_sopr"], cfg["sth"]),
        "cycle_heat": _cycle_heat(values["lth_mvrv"], cfg["lth_mvrv"]),
        "distribution_pressure": _distribution_pressure(distribution, sell_status, cfg["distribution"]),
        "state": state,
        "values": values,
        "streaks": {"sth_stress_days": stress_days, "sth_recovery_days": recovery_days},
    }
