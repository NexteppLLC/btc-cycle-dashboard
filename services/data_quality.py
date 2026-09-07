"""Shared, deterministic selection of measured observations for scoring and display.

Price providers and proxy instruments are never spliced into a synthetic history.
Freshness uses the observation's effective date, never its download timestamp.
"""
from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Any

import pandas as pd

from indicators.normalization import finite_number


MAX_AGE_DAYS = {"btc_price_usd": 3, "gold_price_usd": 5, "silver_price_usd": 5,
                "etf_flow_usd": 5}


def field(row: Any, name: str, default=None):
    return row.get(name, default) if isinstance(row, dict) else getattr(row, name, default)


def as_date(value) -> date | None:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def observation_date(row) -> date | None:
    for key in ("effective_date", "date", "timestamp"):
        day = as_date(field(row, key))
        if day is not None:
            return day
    return None


def _source_key(row) -> tuple[str, str]:
    source = str(field(row, "source", ""))
    if source in {"Glassnode availability", "Glassnode API v1 availability",
                  "CALCULATED_FROM_GLASSNODE_PRICE_LTH_MVRV availability"}:
        source = source.removesuffix(" availability")
    # Older databases saved Glassnode failures under an alias different from
    # measured values. Group both identities so failures cannot be bypassed by
    # selecting the same provider's previous successful observation.
    if source == "Glassnode":
        source = ("CALCULATED_FROM_GLASSNODE_PRICE_LTH_MVRV"
                  if field(row, "metric_name") == "lth_realized_price" else "Glassnode API v1")
    return source, str(field(row, "price_type", "") or "")


def _fetched_key(row) -> str:
    value = field(row, "fetched_at")
    return str(value.isoformat() if hasattr(value, "isoformat") else value or "")


def _is_measured(row) -> bool:
    value = finite_number(field(row, "value"))
    if str(field(row, "status", "")) != "OK" or value is None:
        return False
    return value > 0 if str(field(row, "metric_name", "")).endswith("price_usd") else True


def _is_request_diagnostic(row) -> bool:
    if (_source_key(row)[0] not in {"Glassnode API v1", "CALCULATED_FROM_GLASSNODE_PRICE_LTH_MVRV"}
            or str(field(row, "status")) not in {
                "MISSING", "ERROR", "UNAVAILABLE", "UNAVAILABLE_PLAN", "UNAVAILABLE_NO_API_KEY"}):
        return False
    if str(field(row, "source", "")).endswith(" availability"):
        return True
    # Compatibility with request diagnostics in databases written before the
    # dedicated availability source was introduced. Daily observations use
    # midnight; request diagnostics used the precise fetch instant instead.
    timestamp, fetched_at = field(row, "timestamp"), field(row, "fetched_at")
    return (isinstance(timestamp, datetime) and timestamp == fetched_at
            and any((timestamp.hour, timestamp.minute, timestamp.second, timestamp.microsecond)))


def _provider_rows(rows, metric_name, as_of, *, include_request_diagnostics=True):
    groups = defaultdict(dict)
    latest_success = {}
    relevant = []
    for row in rows:
        if field(row, "metric_name") != metric_name:
            continue
        day = observation_date(row)
        if day is None or day > as_of:
            continue
        key = _source_key(row)
        relevant.append((row, day, key))
        if _is_measured(row):
            latest_success[key] = max(latest_success.get(key, ""), _fetched_key(row))
    for row, day, key in relevant:
        # PENDING describes an unpublished current-day cell, not a measured
        # null. A historical missing cell remains in the series and blocks
        # current selection. Freshness still uses the last observation's date.
        if (str(field(row, "status")) == "PENDING" and day == as_of
                and key[0] == "Coin Metrics Community API v4"):
            continue
        # Request diagnostics use their fetch instant as timestamp. A later
        # successful fetch can recover a daily series even when the newest
        # published observation is still yesterday. Actual dated missing/error
        # observations are never removed by this recovery path.
        if _is_request_diagnostic(row) and (not include_request_diagnostics
                                           or _fetched_key(row) < latest_success.get(key, "")):
            continue
        previous = groups[key].get(day)
        if previous is None or _fetched_key(row) > _fetched_key(previous):
            groups[key][day] = row
    return groups


def _selected_provider(rows, metric_name, as_of):
    groups = _provider_rows(rows, metric_name, as_of)
    candidates = []
    for key, dated in groups.items():
        usable = [day for day, row in dated.items() if _is_measured(row)]
        if not usable:
            continue
        # At equal freshness prefer native spot, then futures, then an ETF proxy.
        price_type = key[1].upper()
        priority = 2 if price_type == "SPOT" else 1 if price_type in {"FUTURES", "FUTURES_PROXY"} else 0
        latest = max(dated)
        current = _is_measured(dated[latest]) and (as_of - latest).days <= MAX_AGE_DAYS.get(metric_name, 3)
        candidates.append(((current, max(usable), priority, key), key))
    if not candidates:
        # Health diagnostics still need a concrete latest failure when no
        # provider has any usable measured observations.
        if not groups:
            return {}
        key = max(groups, key=lambda key: (max(groups[key]),
                  _fetched_key(groups[key][max(groups[key])]), key))
        return groups[key]
    return groups[max(candidates)[1]]


def selected_metric_rows(rows, metric_name: str, as_of: date | None = None) -> list:
    """Measured chart history; request failures cannot erase an observation."""
    as_of = as_of or datetime.now(timezone.utc).date()
    dated = _selected_provider(rows, metric_name, as_of)
    if not dated:
        return []
    key = _source_key(dated[max(dated)])
    history = _provider_rows(rows, metric_name, as_of, include_request_diagnostics=False).get(key, {})
    return [history[day] for day in sorted(history) if _is_measured(history[day])]


def latest_metric_record(rows, metric_name: str, as_of: date | None = None):
    """Latest selected-provider record after recovery/publication filtering.

    This may be a failure diagnostic or stale measured value. It intentionally
    applies no freshness gate so health reporting can distinguish those cases.
    """
    as_of = as_of or datetime.now(timezone.utc).date()
    dated = _selected_provider(rows, metric_name, as_of)
    return dated[max(dated)] if dated else None


def metric_series(rows, metric_name: str, as_of: date | None = None) -> pd.Series:
    """Single-provider dated history; explicit missing observations remain NaN."""
    as_of = as_of or datetime.now(timezone.utc).date()
    dated = _selected_provider(rows, metric_name, as_of)
    return pd.Series({day: finite_number(field(dated[day], "value")) if _is_measured(dated[day]) else None
                      for day in sorted(dated)}, dtype=float)


def current_metric_row(rows, metric_name: str, as_of: date | None = None,
                       max_age_days: int | None = None):
    """Current measured row, or None on stale, failed, missing or future inputs."""
    as_of = as_of or datetime.now(timezone.utc).date()
    dated = _selected_provider(rows, metric_name, as_of)
    if not dated:
        return None
    latest_day = max(dated)
    latest = dated[latest_day]
    maximum = MAX_AGE_DAYS.get(metric_name, 3) if max_age_days is None else max_age_days
    return latest if _is_measured(latest) and (as_of - latest_day).days <= maximum else None


def metric_current(rows, metric_name: str, as_of: date | None = None,
                   max_age_days: int | None = None) -> float | None:
    row = current_metric_row(rows, metric_name, as_of, max_age_days)
    return finite_number(field(row, "value")) if row is not None else None
