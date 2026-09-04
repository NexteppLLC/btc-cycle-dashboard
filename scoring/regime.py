"""Multi-signal phase, confidence, warnings and future alert events."""

PHASE_JA = {"BEAR": "弱気相場", "ACCUMULATION": "底値・蓄積", "EARLY_BULL": "上昇初期", "MID_BULL": "上昇中期", "LATE_BULL": "上昇後期", "TOP_RISK": "天井警戒", "DISTRIBUTION": "分配局面", "PARTIAL": "判定保留", "UNKNOWN": "データ不足"}


def weighted_confidence(available: dict[str, bool], weights: dict[str, float]) -> float:
    """Completeness of decision-critical inputs, not a count of API responses."""
    total = sum(weights.values())
    return round(100 * sum(weight for name, weight in weights.items() if available.get(name)) / total, 1) if total else 0.0


def btc_minimum_data(values: dict) -> tuple[bool, list[str]]:
    major = ("lth_mvrv", "sth_mvrv", "lth_distribution", "mvrv_zscore")
    missing = []
    if values.get("btc_price_usd") is None: missing.append("Price")
    if values.get("btc_trend") is None: missing.append("Trend")
    present = sum(values.get(x) is not None for x in major)
    if present < 2: missing.append(f"On-chain major metrics ({present}/2)")
    return not missing, missing


def classify_phase(cycle: float | None, top: float | None, trend: float | None, distribution: float | None, sth_mvrv: float | None, cfg: dict, *, minimum_met: bool = True, confidence: float = 100) -> str:
    if not minimum_met or confidence < cfg.get("minimum_data", {}).get("phase_confidence", 50): return "PARTIAL"
    if cycle is None or trend is None: return "UNKNOWN"
    p = cfg["phase"]
    if distribution is not None and distribution >= p["distribution"] and (top or 0) >= p["top_risk"]: return "DISTRIBUTION"
    if (top or 0) >= p["top_risk"]: return "TOP_RISK"
    if trend < 0 and (sth_mvrv is None or sth_mvrv < 1): return "BEAR"
    if cycle >= p["late_bull"] and trend > 0: return "LATE_BULL"
    if cycle >= p["mid_bull"] and trend > 0 and (sth_mvrv is None or sth_mvrv >= 1): return "MID_BULL"
    if cycle >= p["early_bull"] and trend > 0: return "EARLY_BULL"
    return "ACCUMULATION"


def calculate_confidence(*, coverage: float, glassnode: bool, etf_current: bool, stale_count: int = 0, history_sufficient: bool = True, contradictory: bool = False, config: dict) -> float:
    p = config["confidence"]; score = 100 * coverage
    if not glassnode: score -= p["glassnode_penalty"]
    if not etf_current: score -= p["etf_pending_penalty"]
    score -= stale_count * p["stale_penalty"]
    if not history_sufficient: score -= p["history_penalty"]
    if contradictory: score -= p["contradiction_penalty"]
    return round(max(0, min(100, score)), 1)


def detect_alerts(values: dict, config: dict) -> list[str]:
    w = config["warnings"]; alerts = []
    if (values.get("top_risk") or 0) >= 70: alerts.append("TOP_RISK_70")
    if (values.get("top_risk") or 0) >= 80: alerts.append("TOP_RISK_80")
    if (values.get("lth_distribution") or 0) >= 70: alerts.append("LTH_DISTRIBUTION_70")
    if values.get("sth_mvrv") is not None and values["sth_mvrv"] < w["sth_profitability"]: alerts.append("STH_MVRV_BELOW_1")
    if values.get("etf_flow_7d") is not None and values["etf_flow_7d"] < w["etf_7d_negative"]: alerts.append("ETF_7D_NEGATIVE")
    if values.get("previous_phase") and values.get("phase") != values["previous_phase"]: alerts.append("CYCLE_PHASE_CHANGE")
    return alerts
