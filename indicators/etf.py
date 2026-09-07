"""ETF rolling aggregates without filling missing days with zero."""
import numpy as np
import pandas as pd

from .normalization import finite_number


def etf_aggregates(flows: pd.Series) -> dict[str, float | None]:
    values = pd.to_numeric(flows, errors="coerce").replace([np.inf, -np.inf], np.nan)

    def agg(n: int, mean: bool = False):
        window = values.iloc[-n:]
        if len(window) < n or window.count() < n:
            return None
        return finite_number(window.mean() if mean else window.sum(min_count=n))

    return {"today": None if values.empty else finite_number(values.iloc[-1]),
            "3d": agg(3), "7d": agg(7), "30d": agg(30),
            "avg_7d": agg(7, True), "avg_30d": agg(30, True)}
