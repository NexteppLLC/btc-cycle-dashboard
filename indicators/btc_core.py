"""BTC Core 5 calculations.

This module is deliberately independent from Cycle Score.  Unknown data stays
unknown: none of the helpers forward-fill observations or treat missing values
as a low-risk signal.
"""
from __future__ import annotations

from datetime import date, timedelta
from math import isfinite


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


def sell_side_flags(value, percentile, config=None):
    config = config or {}
    fixed_high = float(config.get("high", .0075))
    fixed_compression = float(config.get("compression", .001))
    pct_high = float(config.get("percentile_high", .90))
    pct_compression = float(config.get("percentile_compression", .10))
    pct_extreme = float(config.get("percentile_extreme", .95))
    value, percentile = number(value), number(percentile)
    high = True if ((value is not None and value >= fixed_high) or
                    (percentile is not None and percentile >= pct_high)) else (
                    False if value is not None and value < fixed_high and percentile is not None and percentile < pct_high else None)
    compression = True if ((value is not None and value <= fixed_compression) or
                           (percentile is not None and percentile <= pct_compression)) else (
                           False if value is not None and value > fixed_compression and percentile is not None and percentile > pct_compression else None)
    extreme = percentile is not None and percentile >= pct_extreme
    return high, compression, extreme


def short_term_state(sth_mvrv, sth_sopr, break_even=1.0) -> str:
    m, s = number(sth_mvrv), number(sth_sopr)
    if m is None or s is None: return "PARTIAL"
    if m < break_even and s < break_even: return "STRESS"
    if m >= break_even and s < break_even: return "RECOVERY"
    if m >= break_even and s >= break_even: return "HEALTHY"
    return "MIXED"


def core_state(values: dict, distribution_coverage: float, config=None) -> tuple[str, list[str]]:
    if isinstance(config, (int, float)):
        config = {"distribution_minimum_coverage": config}
    config = config or {}
    minimum_coverage = float(config.get("distribution_minimum_coverage", 1.0))
    break_even = float(config.get("sth_break_even", 1.0))
    lth_high = float(config.get("lth_mvrv", {}).get("high", 3.5))
    distribution_high = float(config.get("distribution", {}).get("high", 70))
    required = ("sth_mvrv", "sth_sopr", "lth_mvrv", "distribution", "sell_side_risk")
    missing = [name for name in required if number(values.get(name)) is None]
    dates = {values.get(f"{name}_date") for name in required if values.get(f"{name}_date") is not None}
    reasons = []
    if missing: reasons.append("欠損: " + ", ".join(missing))
    if distribution_coverage < minimum_coverage: reasons.append(f"Distribution入力充足率 {distribution_coverage:.0%}")
    if len(dates) > 1 or len(dates) < 1: reasons.append("Core 5の観測日が一致しません")
    m, s, l, d = (number(values.get(k)) for k in ("sth_mvrv", "sth_sopr", "lth_mvrv", "distribution"))
    high, _, _ = sell_side_flags(values.get("sell_side_risk"), values.get("sell_side_percentile_4y"), config.get("sell_side_risk"))
    if missing or distribution_coverage < minimum_coverage or len(dates) != 1:
        return "PARTIAL", reasons or ["必要入力を確認できません"]
    # Evaluate in priority order with three-valued logic. A true branch does
    # not require an unrelated percentile merely to prove the same OR clause.
    distribution_risk = True if d >= distribution_high and (l >= lth_high or high is True) else (
        None if d >= distribution_high and l < lth_high and high is None else False)
    if distribution_risk is True:
        return "DISTRIBUTION_RISK", reasons
    if distribution_risk is None:
        return "PARTIAL", ["最優先のDISTRIBUTION_RISKを除外できません"]
    if m < break_even and s < break_even:
        return "STRESS", reasons
    overheated = True if l >= lth_high or high is True else (None if high is None else False)
    if overheated is True:
        return "OVERHEATED", reasons + (["Sell-Sideのみの場合は実現損益の拡大に警戒"] if l < lth_high else [])
    if overheated is None:
        return "PARTIAL", ["OVERHEATEDを除外できません"]
    if m > break_even and s >= break_even and l < lth_high and d < distribution_high and high is False: return "HEALTHY_BULL", []
    if m >= break_even and s >= break_even and d < distribution_high: return "RECOVERY", []
    return "MIXED", []


def alerts(current: dict, histories: dict[str, dict[date, float | None]], config=None,
           distribution_coverage=1.0) -> list[dict]:
    config = config or {}
    break_even = float(config.get("sth_break_even", 1.0))
    lth_high = float(config.get("lth_mvrv", {}).get("high", 3.5))
    dist_cfg = config.get("distribution", {})
    dist_high, dist_extreme = float(dist_cfg.get("high", 70)), float(dist_cfg.get("extreme", 80))
    minimum = float(config.get("distribution_minimum_coverage", 1.0))
    result = []
    def add(alert_id, severity, day, reason): result.append({"id": alert_id, "severity": severity, "observation_date": day, "reason": reason})
    m, s, l, d, risk = (number(current.get(k)) for k in
                         ("sth_mvrv", "sth_sopr", "lth_mvrv", "distribution", "sell_side_risk"))
    sth_day = current.get("sth_mvrv_date") if current.get("sth_mvrv_date") == current.get("sth_sopr_date") else None
    if isinstance(sth_day, date):
        pm = number(histories.get("sth_mvrv", {}).get(sth_day - timedelta(days=1)))
        ps = number(histories.get("sth_sopr", {}).get(sth_day - timedelta(days=1)))
        if None not in (m, s, pm, ps) and m < break_even and s < break_even and pm < break_even and ps < break_even: add("BTC5_STH_STRESS", "HIGH", sth_day, "STH-MVRVとSTH-SOPRが2連続暦日で損益分岐未満")
        if None not in (m, s, pm, ps) and m >= break_even and s >= break_even and pm >= break_even and ps >= break_even: add("BTC5_STH_RECOVERY", "INFO", sth_day, "STH-MVRVとSTH-SOPRが2連続暦日で損益分岐以上")
    lth_day, dist_day, risk_day = (current.get(f"{name}_date") for name in ("lth_mvrv", "distribution", "sell_side_risk"))
    if l is not None and isinstance(lth_day, date) and l >= lth_high: add("BTC5_LTH_HEAT_HIGH", "HIGH", lth_day, f"LTH-MVRVが{lth_high:g}以上")
    dist_valid = d is not None and isinstance(dist_day, date) and distribution_coverage >= minimum
    if dist_valid and d >= dist_high: add("BTC5_LTH_DISTRIBUTION_HIGH", "EXTREME" if d >= dist_extreme else "HIGH", dist_day, f"Distributionが{dist_high:g}以上")
    high, compression, extreme = sell_side_flags(risk, current.get("sell_side_percentile_4y"), config.get("sell_side_risk"))
    if isinstance(risk_day, date) and compression: add("BTC5_SELL_SIDE_COMPRESSION", "INFO", risk_day, "固定値または4年PercentileがCompression域")
    if isinstance(risk_day, date) and high: add("BTC5_SELL_SIDE_HIGH", "EXTREME" if extreme else "HIGH", risk_day, "固定値または4年PercentileがHigh域")
    heat_same_day = l is not None and l >= lth_high and lth_day == dist_day
    sell_same_day = high is True and risk_day == dist_day
    if dist_valid and d >= dist_high and (heat_same_day or sell_same_day): add("BTC5_DISTRIBUTION_RISK", "EXTREME" if d >= dist_extreme or extreme else "HIGH", dist_day, "Distribution高水準かつ同日LTH HeatまたはSell-Side High")
    return result
