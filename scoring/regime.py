"""Multi-signal phase, confidence, warnings and future alert events."""
from indicators.normalization import finite_number

PHASE_JA = {"BEAR": "弱気相場", "ACCUMULATION": "底値・蓄積", "EARLY_BULL": "上昇初期", "MID_BULL": "上昇中期", "LATE_BULL": "上昇後期", "TOP_RISK": "天井警戒", "DISTRIBUTION": "分配局面", "PARTIAL": "判定保留", "UNKNOWN": "データ不足"}


def weighted_confidence(available: dict[str, bool | float], weights: dict[str, float]) -> float:
    """Completeness of inputs, including fractional coverage of composites."""
    valid_weights = {name: weight for name, raw in weights.items()
                     if (weight := finite_number(raw)) is not None and weight > 0}
    total = sum(valid_weights.values())
    if not total or finite_number(total) is None:
        return 0.0
    score = 0.0
    for name, weight in valid_weights.items():
        raw = available.get(name)
        coverage = float(raw) if isinstance(raw, bool) else finite_number(raw)
        if coverage is not None:
            score += weight / total * min(1.0, max(0.0, coverage))
    return round(min(100.0, max(0.0, 100 * score)), 1)


def btc_minimum_data(values: dict) -> tuple[bool, list[str]]:
    major = ("lth_mvrv", "sth_mvrv", "lth_distribution", "mvrv_zscore")
    missing = []
    price = finite_number(values.get("btc_price_usd"))
    if price is None or price <= 0: missing.append("Price")
    if finite_number(values.get("btc_trend")) is None: missing.append("Trend")
    present = sum(finite_number(values.get(x)) is not None for x in major)
    if present < 2: missing.append(f"On-chain major metrics ({present}/2)")
    return not missing, missing


def classify_phase(cycle: float | None, top: float | None, trend: float | None, distribution: float | None, sth_mvrv: float | None, cfg: dict, *, minimum_met: bool = True, confidence: float = 100) -> str:
    cycle, top, trend, distribution, sth_mvrv, confidence = (
        finite_number(value) for value in (cycle, top, trend, distribution, sth_mvrv, confidence)
    )
    if not minimum_met or confidence is None or confidence < cfg.get("minimum_data", {}).get("phase_confidence", 50): return "PARTIAL"
    if cycle is None or trend is None: return "UNKNOWN"
    p = cfg["phase"]
    if distribution is not None and distribution >= p["distribution"] and top is not None and top >= p["top_risk"]: return "DISTRIBUTION"
    if top is not None and top >= p["top_risk"]: return "TOP_RISK"
    if trend < 0 and (sth_mvrv is None or sth_mvrv < 1): return "BEAR"
    if cycle >= p["late_bull"] and trend > 0: return "LATE_BULL"
    if cycle >= p["mid_bull"] and trend > 0 and (sth_mvrv is None or sth_mvrv >= 1): return "MID_BULL"
    if cycle >= p["early_bull"] and trend > 0: return "EARLY_BULL"
    return "ACCUMULATION"


def calculate_confidence(*, coverage: float, glassnode: bool, etf_current: bool, stale_count: int = 0, history_sufficient: bool = True, contradictory: bool = False, config: dict) -> float:
    coverage = finite_number(coverage)
    if coverage is None: return 0.0
    coverage = min(1.0, max(0.0, coverage))
    p = config["confidence"]; score = 100 * coverage
    if not glassnode: score -= p["glassnode_penalty"]
    if not etf_current: score -= p["etf_pending_penalty"]
    score -= stale_count * p["stale_penalty"]
    if not history_sufficient: score -= p["history_penalty"]
    if contradictory: score -= p["contradiction_penalty"]
    return round(max(0, min(100, score)), 1)


def detect_alerts(values: dict, config: dict) -> list[str]:
    w = config["warnings"]; alerts = []
    numbers = {key: finite_number(values.get(key)) for key in
               ("top_risk", "lth_distribution", "sth_mvrv", "lth_mvrv", "mvrv_zscore", "etf_flow_7d")}
    if numbers["top_risk"] is not None and numbers["top_risk"] >= 70: alerts.append("TOP_RISK_70")
    if numbers["top_risk"] is not None and numbers["top_risk"] >= 80: alerts.append("TOP_RISK_80")
    if numbers["lth_distribution"] is not None and numbers["lth_distribution"] >= 70: alerts.append("LTH_DISTRIBUTION_70")
    if numbers["sth_mvrv"] is not None and numbers["sth_mvrv"] < w["sth_profitability"]: alerts.append("STH_MVRV_BELOW_1")
    if numbers["lth_mvrv"] is not None and numbers["lth_mvrv"] >= 3.5: alerts.append("LTH_MVRV_HIGH")
    if numbers["mvrv_zscore"] is not None and numbers["mvrv_zscore"] >= 7: alerts.append("MVRV_Z_EXTREME")
    if values.get("sth_state") == "RECOVERY_CONFIRMATION": alerts.append("STH_RECOVERY")
    if numbers["etf_flow_7d"] is not None and numbers["etf_flow_7d"] < w["etf_7d_negative"]: alerts.append("ETF_7D_NEGATIVE")
    if values.get("previous_phase") and values.get("phase") != values["previous_phase"]: alerts.append("CYCLE_PHASE_CHANGE")
    return alerts
