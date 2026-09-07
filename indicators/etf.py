"""ETF calendar-window aggregates without filling missing weekdays with zero."""
from datetime import date, datetime

import numpy as np
import pandas as pd

from .normalization import finite_number


def etf_aggregates(flows: pd.Series) -> dict[str, float | None]:
    values = pd.to_numeric(flows, errors="coerce").replace([np.inf, -np.inf], np.nan)
    dated = isinstance(values.index, pd.DatetimeIndex) or (
        len(values) > 0 and isinstance(values.index[0], (date, datetime)))
    if dated:
        values = values.copy()
        values.index = pd.to_datetime(values.index, utc=True).normalize()
        values = values.sort_index()
        # A daily total must be unique. Conflicting observations are unknown.
        duplicates = values.index.duplicated(keep=False)
        values.loc[duplicates] = np.nan
        values = values[~values.index.duplicated(keep="last")]

    def agg(n: int, mean: bool = False):
        if dated:
            if values.empty:
                return None
            # Anchor to the latest observation, not seven/thirty trading rows.
            # Weekends need no fabricated zeros; unknown weekdays (including an
            # unverified market holiday) prevent a complete-window claim.
            end = values.index[-1]
            start = end - pd.Timedelta(days=n - 1)
            expected = pd.date_range(start, end, freq="B")
            if values.reindex(expected).isna().any():
                return None
            window = values.loc[start:end]
            if window.empty or window.isna().any():
                return None
        else:
            # Undated callers can only request observation-count windows.
            window = values.iloc[-n:]
            if len(window) < n or window.count() < n:
                return None
        return finite_number(window.mean() if mean else window.sum(min_count=1))

    return {"today": None if values.empty else finite_number(values.iloc[-1]),
            "3d": agg(3), "7d": agg(7), "30d": agg(30),
            "avg_7d": agg(7, True), "avg_30d": agg(30, True)}
