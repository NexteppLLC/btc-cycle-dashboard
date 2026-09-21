"""BTC Core 5 calculations.

This module is deliberately independent from Cycle Score.  Unknown data stays
unknown: none of the helpers forward-fill observations or treat missing values
as a low-risk signal.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from math import isfinite
from typing import Iterable


def number(value):
    try:
        value = float(value)
        return value if isfinite(value) else None
    except (TypeError, ValueError, OverflowError):
        return None


def sell_side_raw(profit, loss, realized_cap) -> float | None:
    """Return (profit + loss) / realized cap for validated same-day inputs."""
    profit, loss, realized_cap = map(number, (profit, loss, realized_cap))
    if profit is None or loss is None or realized_cap is None:
        return None
    if profit < 0 or loss < 0 or realized_cap <= 0:
        return None
    return (profit + loss) / realized_cap


def calendar_sma(values: dict[date, float | None], day: date, days: int = 15) -> float | None:
    required = [day - timedelta(days=offset) for offset in range(days)]
    sample = [number(values.get(item)) for item in required]
    return sum(sample) / days if all(value is not None for value in sample) else None


def exact_change(values: dict[date, float | None], day: date, lag: int) -> tuple[float | None, float | None]:
    current, previous = number(values.get(day)), number(values.get(day - timedelta(days=lag)))
    return ((current - previous) if current is not None and previous is not None else None, previous)


def midrank_percentile(values: dict[date, float | None], day: date, start: date,
                       *, required_start: date) -> dict:
    """Inclusive [start, day] midrank; require coverage back to required_start."""
    current = number(values.get(day))
    sample = [number(value) for observed, value in values.items() if start <= observed <= day]
    sample = [value for value in sample if value is not None]
    first = min((observed for observed, value in values.items()
                 if start <= observed <= day and number(value) is not None), default=None)
    expected = (day - required_start).days + 1
    observed_days = {observed for observed, value in values.items()
                     if required_start <= observed <= day and number(value) is not None}
    coverage = len(observed_days) / expected if expected > 0 else 0.0
    complete = current is not None and first is not None and first <= required_start and len(observed_days) == expected
    percentile = None
    if complete:
        below = sum(value < current for value in sample)
        equal = sum(value == current for value in sample)
        percentile = (below + equal / 2) / len(sample)
    return {"value": percentile, "status": "OK" if complete else "INSUFFICIENT_HISTORY",
            "count": len(sample), "expected": expected, "start": start, "end": day,
            "coverage": coverage}


def rolling_percentile(values: dict[date, float | None], day: date, years: int | None = None) -> dict:
    if years is None:  # 52 weeks means the latest 364 calendar days, inclusive.
        start = day - timedelta(days=363)
    else:
        try:
            start = day.replace(year=day.year - years)
        except ValueError:  # 29 February -> 28 February
            start = day.replace(year=day.year - years, day=28)
    return midrank_percentile(values, day, start, required_start=start)


def threshold_label(value, bands, unavailable="PARTIAL") -> str:
    value = number(value)
    if value is None:
        return unavailable
    for upper, label in bands:
        if upper is None or value < upper:
            return label
    return bands[-1][1]


def sell_side_flags(value, percentile):
    value, percentile = number(value), number(percentile)
    high = True if ((value is not None and value >= .0075) or
                    (percentile is not None and percentile >= .90)) else (
                    False if value is not None and value < .0075 and percentile is not None and percentile < .90 else None)
    compression = True if ((value is not None and value <= .001) or
                           (percentile is not None and percentile <= .10)) else (
                           False if value is not None and value > .001 and percentile is not None and percentile > .10 else None)
    extreme = percentile is not None and percentile >= .95
    return high, compression, extreme


def short_term_state(sth_mvrv, sth_sopr) -> str:
    m, s = number(sth_mvrv), number(sth_sopr)
    if m is None or s is None: return "PARTIAL"
    if m < 1 and s < 1: return "STRESS"
    if m >= 1 and s < 1: return "RECOVERY"
    if m >= 1 and s >= 1: return "HEALTHY"
    return "MIXED"


def core_state(values: dict, distribution_coverage: float, minimum_coverage: float = 1.0) -> tuple[str, list[str]]:
    required = ("sth_mvrv", "sth_sopr", "lth_mvrv", "distribution", "sell_side_risk")
    missing = [name for name in required if number(values.get(name)) is None]
    dates = {values.get(f"{name}_date") for name in required if values.get(f"{name}_date") is not None}
    reasons = []
    if missing: reasons.append("欠損: " + ", ".join(missing))
    if distribution_coverage < minimum_coverage: reasons.append(f"Distribution入力充足率 {distribution_coverage:.0%}")
    if len(dates) > 1 or len(dates) < 1: reasons.append("Core 5の観測日が一致しません")
    m, s, l, d = (number(values.get(k)) for k in ("sth_mvrv", "sth_sopr", "lth_mvrv", "distribution"))
    high, _, _ = sell_side_flags(values.get("sell_side_risk"), values.get("sell_side_percentile_4y"))
    if missing or distribution_coverage < minimum_coverage or len(dates) != 1 or high is None:
        return "PARTIAL", reasons or ["高優先度の状態を除外できません"]
    if d >= 70 and (l >= 3.5 or high is True):
        return "DISTRIBUTION_RISK", reasons
    if m < 1 and s < 1:
        return "STRESS", reasons
    if l >= 3.5 or high is True:
        return "OVERHEATED", reasons + (["Sell-Sideのみの場合は実現損益の拡大に警戒"] if l < 3.5 else [])
    if m > 1 and s >= 1 and l < 3.5 and d < 70 and high is False: return "HEALTHY_BULL", []
    if m >= 1 and s >= 1 and d < 70: return "RECOVERY", []
    return "MIXED", []


def alerts(current: dict, histories: dict[str, dict[date, float | None]]) -> list[dict]:
    day = current.get("observation_date")
    if not isinstance(day, date): return []
    result = []
    def add(alert_id, severity, reason): result.append({"id": alert_id, "severity": severity, "observation_date": day, "reason": reason})
    m, s, l, d, risk = (number(current.get(k)) for k in
                         ("sth_mvrv", "sth_sopr", "lth_mvrv", "distribution", "sell_side_risk"))
    pm = number(histories.get("sth_mvrv", {}).get(day - timedelta(days=1)))
    ps = number(histories.get("sth_sopr", {}).get(day - timedelta(days=1)))
    if None not in (m, s, pm, ps) and m < 1 and s < 1 and pm < 1 and ps < 1: add("BTC5_STH_STRESS", "HIGH", "STH-MVRVとSTH-SOPRが2連続暦日で1未満")
    if None not in (m, s, pm, ps) and m >= 1 and s >= 1 and pm >= 1 and ps >= 1: add("BTC5_STH_RECOVERY", "INFO", "STH-MVRVとSTH-SOPRが2連続暦日で1以上")
    if l is not None and l >= 3.5: add("BTC5_LTH_HEAT_HIGH", "HIGH", "LTH-MVRVが3.5以上")
    if d is not None and d >= 70: add("BTC5_LTH_DISTRIBUTION_HIGH", "EXTREME" if d >= 80 else "HIGH", "Distributionが70以上")
    high, compression, extreme = sell_side_flags(risk, current.get("sell_side_percentile_4y"))
    if compression: add("BTC5_SELL_SIDE_COMPRESSION", "INFO", "固定値または4年PercentileがCompression域")
    if high: add("BTC5_SELL_SIDE_HIGH", "EXTREME" if extreme else "HIGH", "固定値または4年PercentileがHigh域")
    if d is not None and d >= 70 and ((l is not None and l >= 3.5) or high): add("BTC5_DISTRIBUTION_RISK", "EXTREME" if d >= 80 or extreme else "HIGH", "Distribution高水準かつLTH HeatまたはSell-Side High")
    return result
