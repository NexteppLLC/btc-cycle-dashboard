"""MVRV derivation only when measured market and realized caps exist."""
def calculate_mvrv(market_cap: float | None, realized_cap: float | None) -> float | None:
    if market_cap is None or realized_cap in (None, 0): return None
    return market_cap / realized_cap
