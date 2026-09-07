"""Conservative technical metrics; insufficient history remains missing."""
import numpy as np
import pandas as pd


def calculate_technicals(prices: pd.Series) -> pd.DataFrame:
    s = pd.to_numeric(prices, errors="coerce").replace([np.inf, -np.inf], np.nan).sort_index()
    s = s.where(s > 0)
    out = pd.DataFrame({"price": s})
    for days in (50, 100, 200, 350, 1400): out[f"ma_{days}"] = s.rolling(days, min_periods=days).mean()
    out["return_7d"] = s.pct_change(7, fill_method=None)
    out["return_30d"] = s.pct_change(30, fill_method=None)
    out["volatility_20d"] = s.pct_change(fill_method=None).rolling(20, min_periods=20).std() * np.sqrt(365)
    delta = s.diff(); gain = delta.clip(lower=0).rolling(14, min_periods=14).mean(); loss = -delta.clip(upper=0).rolling(14, min_periods=14).mean()
    out["rsi_14"] = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
    out.loc[(loss == 0) & (gain > 0), "rsi_14"] = 100.0
    out.loc[(loss == 0) & (gain == 0), "rsi_14"] = 50.0
    out["drawdown_30d"] = s / s.rolling(30, min_periods=30).max() - 1
    out["drawdown_ath"] = s / s.cummax() - 1
    return out.replace([np.inf, -np.inf], np.nan)
