"""Missing-safe normalization helpers."""
import numpy as np
import pandas as pd


def minmax(value: float | None, low: float, high: float) -> float | None:
    if value is None or pd.isna(value): return None
    return float(np.clip((value - low) / (high - low) * 100, 0, 100))


def historical_stats(series: pd.Series, minimum: int = 30) -> dict[str, float | None]:
    clean = pd.to_numeric(series, errors="coerce").dropna()
    if len(clean) < minimum: return {"percentile": None, "zscore": None}
    current = clean.iloc[-1]
    std = clean.std()
    return {"percentile": float((clean <= current).mean()), "zscore": None if not std else float((current - clean.mean()) / std)}


def multi_horizon_stats(series: pd.Series) -> dict[str, float | None]:
    """52-week, four-year, full-history percentiles and 365d rolling z-score."""
    clean = pd.to_numeric(series, errors="coerce").dropna()
    def pct(window: int, minimum: int):
        sample = clean.tail(window)
        return None if len(sample) < minimum else float((sample <= sample.iloc[-1]).mean())
    full = None if len(clean) < 30 else float((clean <= clean.iloc[-1]).mean())
    roll = clean.tail(365)
    z = None if len(roll) < 30 or not roll.std() else float((roll.iloc[-1] - roll.mean()) / roll.std())
    return {"percentile_52w": pct(365, 30), "percentile_4y": pct(1461, 365),
            "percentile_all": full, "rolling_zscore": z}


def change_summary(series: pd.Series) -> dict[str, float | None]:
    clean = pd.to_numeric(series, errors="coerce")
    current = clean.iloc[-1] if len(clean) else None
    def at(days: int): return clean.iloc[-days - 1] if len(clean) > days and pd.notna(clean.iloc[-days - 1]) else None
    prev, d7, d30 = at(1), at(7), at(30)
    diff = lambda old: None if old is None or pd.isna(current) else float(current - old)
    return {"current": None if current is None or pd.isna(current) else float(current), "previous": prev, "daily_change": diff(prev), "seven_days_ago": d7, "change_7d": diff(d7), "change_30d": diff(d30), **historical_stats(clean)}
