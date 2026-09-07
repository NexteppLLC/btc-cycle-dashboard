"""MVRV derivation only when measured market and realized caps exist."""
from .normalization import finite_number


def calculate_mvrv(market_cap: float | None, realized_cap: float | None) -> float | None:
    market_cap, realized_cap = finite_number(market_cap), finite_number(realized_cap)
    if market_cap is None or realized_cap is None or realized_cap <= 0 or market_cap <= 0:
        return None
    return finite_number(market_cap / realized_cap)
