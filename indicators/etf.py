"""ETF rolling aggregates without filling missing days with zero."""
import pandas as pd


def etf_aggregates(flows: pd.Series) -> dict[str, float | None]:
    clean = pd.to_numeric(flows, errors="coerce").dropna()
    def agg(n, mean=False):
        if len(clean) < n: return None
        return float(clean.iloc[-n:].mean() if mean else clean.iloc[-n:].sum())
    return {"today": None if clean.empty else float(clean.iloc[-1]), "3d": agg(3), "7d": agg(7), "30d": agg(30), "avg_7d": agg(7, True), "avg_30d": agg(30, True)}

