"""Missing-safe normalization helpers."""
import math

import numpy as np
import pandas as pd


def finite_number(value: object) -> float | None:
    """Return a finite numeric scalar; unavailable or invalid values stay missing."""
    if value is None or isinstance(value, (bool, np.bool_)):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def minmax(value: float | None, low: float, high: float) -> float | None:
    value, low, high = (finite_number(x) for x in (value, low, high))
    if value is None or low is None or high is None or low == high:
        return None
    # Descending ranges intentionally support inverse indicators.
    if (high > low and value <= low) or (high < low and value >= low):
        return 0.0
    if (high > low and value >= high) or (high < low and value <= high):
        return 100.0
    numerator, span = value - low, high - low
    # Halving keeps a very large, opposite-sign range finite.
    if finite_number(span) is None:
        numerator, span = value / 2 - low / 2, high / 2 - low / 2
    score = finite_number(numerator / span * 100)
    return None if score is None else min(100.0, max(0.0, score))


def _finite_series(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan)


def historical_stats(series: pd.Series, minimum: int = 30) -> dict[str, float | None]:
    values = _finite_series(series)
    current = finite_number(values.iloc[-1]) if len(values) else None
    clean = values.dropna()
    if current is None or len(clean) < minimum:
        return {"percentile": None, "zscore": None}
    std = finite_number(clean.std())
    zscore = None if std in (None, 0) else finite_number((current - clean.mean()) / std)
    return {"percentile": float((clean <= current).mean()), "zscore": zscore}


def multi_horizon_stats(series: pd.Series) -> dict[str, float | None]:
    """52-week, four-year, full-history percentiles and 365d rolling z-score."""
    values = _finite_series(series)
    current = finite_number(values.iloc[-1]) if len(values) else None

    def pct(window: int, minimum: int):
        sample = values.tail(window).dropna()
        return None if current is None or len(sample) < minimum else float((sample <= current).mean())

    roll = values.tail(365).dropna()
    std = finite_number(roll.std()) if len(roll) >= 30 else None
    z = None if current is None or std in (None, 0) else finite_number((current - roll.mean()) / std)
    return {"percentile_52w": pct(365, 30), "percentile_4y": pct(1461, 365),
            "percentile_all": pct(len(values), 30), "rolling_zscore": z}


def change_summary(series: pd.Series) -> dict[str, float | None]:
    clean = _finite_series(series)
    current = finite_number(clean.iloc[-1]) if len(clean) else None

    def at(days: int):
        return finite_number(clean.iloc[-days - 1]) if len(clean) > days else None

    def diff(old: float | None):
        return None if old is None or current is None else finite_number(current - old)

    prev, d7, d30 = at(1), at(7), at(30)
    return {"current": current, "previous": prev, "daily_change": diff(prev),
            "seven_days_ago": d7, "change_7d": diff(d7), "change_30d": diff(d30),
            **historical_stats(clean)}
