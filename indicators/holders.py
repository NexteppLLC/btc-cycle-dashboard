"""Long-term-holder distribution composite."""
from .normalization import finite_number, minmax


def distribution_score(values: dict[str, float | None]) -> tuple[float | None, float]:
    specs = {"lth_spent_volume_z": (0, 3, .30), "lth_sopr": (1, 2, .25), "lth_realized_profit_z": (0, 3, .20), "lth_supply_change_pct": (0, -3, .15), "cdd_z": (0, 3, .10)}
    available = []
    for name, (low, high, weight) in specs.items():
        score = minmax(values.get(name), low, high)
        if score is not None: available.append((score, weight))
    if not available: return None, 0.0
    weight_sum = sum(w for _, w in available)
    return round(sum(s * w for s, w in available) / weight_sum, 2), round(weight_sum, 2)


def sth_state(values: dict[str, float | None]) -> str | None:
    """Classify STH stress/recovery without substituting missing observations."""
    mvrv, sopr, cost, price = (finite_number(values.get(k)) for k in
                               ("sth_mvrv", "sth_sopr", "sth_realized_price", "btc_price_usd"))
    if mvrv is not None and sopr is not None and mvrv < 1 and sopr < 1:
        return "STH_STRESS"
    if mvrv is not None and cost is not None and price is not None and price >= cost and mvrv > 1:
        return "RECOVERY_CONFIRMATION"
    return None
