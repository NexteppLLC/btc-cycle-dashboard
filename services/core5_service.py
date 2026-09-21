"""One read-time source of truth for the BTC 5-Signal UI and reports."""
from __future__ import annotations

from datetime import date, datetime, timezone

from indicators.btc_core import (alerts, core_state, exact_change, number,
                                 rolling_percentile, sell_side_flags,
                                 short_term_state, threshold_label)
from services.data_quality import (current_metric_row, field, latest_metric_record,
                                   metric_series, observation_date)


METRICS = {"sth_mvrv": "sth_mvrv", "sth_sopr": "sth_sopr",
           "lth_mvrv": "lth_mvrv", "sell_side_risk": "sell_side_risk_15d"}


def _series(metrics, name, as_of):
    series = metric_series(metrics, name, as_of)
    return {index if isinstance(index, date) else index.date(): number(value)
            for index, value in series.items()}


def build_core5(metrics, snapshots, cfg: dict, as_of: date | None = None) -> dict:
    as_of = as_of or datetime.now(timezone.utc).date()
    minimum = float(cfg.get("distribution_minimum_coverage", 1.0))
    histories = {key: _series(metrics, name, as_of) for key, name in METRICS.items()}
    dist_history = {field(row, "lth_distribution_observed_date"):
                    number(field(row, "lth_distribution")) for row in snapshots
                    if field(row, "lth_distribution_observed_date") is not None
                    and field(row, "lth_distribution_observed_date") <= as_of}
    histories["distribution"] = dist_history
    cards, values = {}, {}
    for key, metric in METRICS.items():
        row = current_metric_row(metrics, metric, as_of)
        diagnostic = row or latest_metric_record(metrics, metric, as_of)
        day = observation_date(row) if row is not None else None
        diagnostic_day = observation_date(diagnostic)
        value = number(field(row, "value")) if row is not None else None
        values[key], values[f"{key}_date"] = value, day
        one, previous_1d = exact_change(histories[key], day, 1) if day else (None, None)
        seven, previous_7d = exact_change(histories[key], day, 7) if day else (None, None)
        pct52 = rolling_percentile(histories[key], day) if day else _missing_stat(as_of, 364)
        diagnostic_status = str(field(diagnostic, "status", "UNAVAILABLE"))
        if row is None and diagnostic_status == "OK" and diagnostic_day is not None:
            diagnostic_status = "STALE"
        reason = field(diagnostic, "error")
        if diagnostic_status == "STALE": reason = f"観測日から{(as_of - diagnostic_day).days}暦日経過（上限3日）"
        cards[key] = {"value": value, "date": day or diagnostic_day, "status": "OK" if row is not None else diagnostic_status,
                      "reason": reason, "source": field(diagnostic, "source"), "fetched_at": field(diagnostic, "fetched_at"),
                      "change_1d": one, "previous_1d": previous_1d,
                      "change_7d": seven, "previous_7d": previous_7d, "percentile_52w": pct52}
    latest_snapshot = max((row for row in snapshots if field(row, "date") <= as_of),
                          key=lambda row: field(row, "date"), default=None)
    # Never substitute the calculation/snapshot date for an unknown input
    # observation date. A legacy or mismatched snapshot is display history only.
    dist_day = field(latest_snapshot, "lth_distribution_observed_date") if latest_snapshot else None
    dist_age_ok = dist_day is not None and 0 <= (as_of - dist_day).days <= 3
    distribution = number(field(latest_snapshot, "lth_distribution")) if dist_age_ok else None
    coverage = number(field(latest_snapshot, "lth_distribution_coverage"))
    coverage = coverage if coverage is not None else 0.0
    values.update(distribution=distribution, distribution_date=dist_day if dist_age_ok else None)
    one, p1 = exact_change(dist_history, dist_day, 1) if dist_day else (None, None)
    seven, p7 = exact_change(dist_history, dist_day, 7) if dist_day else (None, None)
    cards["distribution"] = {"value": distribution, "date": dist_day, "status": "OK" if dist_age_ok else "UNAVAILABLE",
        "coverage": coverage, "change_1d": one, "previous_1d": p1, "change_7d": seven, "previous_7d": p7,
        "percentile_52w": rolling_percentile(dist_history, dist_day) if dist_day else _missing_stat(as_of, 364)}
    risk_day = values.get("sell_side_risk_date")
    pct4 = rolling_percentile(histories["sell_side_risk"], risk_day, 4) if risk_day else _missing_stat(as_of, 1461)
    cards["sell_side_risk"]["percentile_4y"] = pct4
    values["sell_side_percentile_4y"] = pct4["value"]
    # All five compare the same confirmed UTC observation date.
    dates = [values.get(f"{name}_date") for name in ("sth_mvrv", "sth_sopr", "lth_mvrv", "distribution", "sell_side_risk")]
    observation = dates[0] if dates and all(day == dates[0] and day is not None for day in dates) else None
    state, reasons = core_state(values, coverage, cfg)
    lth_cfg, dist_cfg = cfg.get("lth_mvrv", {}), cfg.get("distribution", {})
    lth_heat = threshold_label(values.get("lth_mvrv"), [(float(lth_cfg.get("capitulation", 1)), "CAPITULATION"),
        (float(lth_cfg.get("low_early", 2)), "LOW_EARLY"), (float(lth_cfg.get("high", 3.5)), "NORMAL_BULL"),
        (float(lth_cfg.get("extreme", 5)), "HIGH"), (None, "EXTREME")])
    dist_pressure = threshold_label(distribution, [(float(dist_cfg.get("low", 40)), "LOW"),
        (float(dist_cfg.get("rising", 60)), "NORMAL"), (float(dist_cfg.get("high", 70)), "RISING"),
        (float(dist_cfg.get("extreme", 80)), "HIGH"), (None, "EXTREME")])
    high, _, extreme = sell_side_flags(values.get("sell_side_risk"), values.get("sell_side_percentile_4y"), cfg.get("sell_side_risk"))
    if coverage < minimum or distribution is None:
        dist_pressure = "PARTIAL"
    elif extreme:
        dist_pressure = "EXTREME"
    elif high and dist_pressure not in {"EXTREME", "HIGH"}:
        dist_pressure = "HIGH"
    current = {**values, "observation_date": observation}
    return {"state": state, "reasons": reasons, "observation_date": observation, "cards": cards,
            "substates": {"short_term_health": short_term_state(values.get("sth_mvrv"), values.get("sth_sopr"), float(cfg.get("sth_break_even", 1))),
                          "cycle_heat": lth_heat, "distribution_pressure": dist_pressure},
            "distribution_coverage": coverage, "minimum_distribution_coverage": minimum,
            "alerts": alerts(current, histories, cfg, coverage)}


def _missing_stat(day, expected):
    return {"value": None, "status": "INSUFFICIENT_HISTORY", "count": 0, "expected": expected,
            "start": None, "end": day, "coverage": 0.0}
