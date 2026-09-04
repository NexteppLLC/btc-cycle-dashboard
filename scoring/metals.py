"""Transparent, missing-safe institutional-flow scoring for precious metals."""
from dataclasses import dataclass
from math import sqrt
from statistics import mean, pstdev


@dataclass
class MetalScores:
    demand: float | None
    top_risk: float | None
    dip_quality: float | None
    phase: str
    divergence: str
    confidence: float
    details: list[dict]


def percentile(history: list[float], value: float, minimum: int = 20) -> float | None:
    clean = [float(x) for x in history if x is not None]
    if len(clean) < minimum: return None
    return 100 * sum(x <= value for x in clean) / len(clean)


def zscore(history: list[float], value: float, minimum: int = 20) -> float | None:
    clean = [float(x) for x in history if x is not None]
    if len(clean) < minimum or not pstdev(clean): return None
    return (value - mean(clean)) / pstdev(clean)


def position_statistics(rows: list[dict]) -> dict:
    """Compute weekly changes and 52W/3Y/full distributions without interpolation."""
    rows = sorted(rows, key=lambda x: x["report_date"]); nets = [x.get("net") for x in rows]
    if not rows or nets[-1] is None: return {}
    current = nets[-1]
    change = lambda weeks: current - nets[-1-weeks] if len(nets) > weeks and nets[-1-weeks] is not None else None
    oi = rows[-1].get("open_interest")
    return {"long": rows[-1].get("long"), "short": rows[-1].get("short"), "net": current,
        "net_oi": current / oi if oi else None, "long_oi": rows[-1].get("long") / oi if oi and rows[-1].get("long") is not None else None,
        "short_oi": rows[-1].get("short") / oi if oi and rows[-1].get("short") is not None else None,
        "change_1w": change(1), "change_4w": change(4), "change_13w": change(13), "zscore": zscore(nets, current),
        "percentile_52w": percentile(nets[-52:], current), "percentile_3y": percentile(nets[-156:], current, 52),
        "percentile_full": percentile(nets, current), "open_interest": oi,
        "oi_change_1w": oi - rows[-2].get("open_interest") if len(rows)>1 and oi is not None and rows[-2].get("open_interest") is not None else None}


def detect_divergence(price_change, mm_change, etf_change, oi_change, commercial_change) -> str:
    bearish = price_change is not None and price_change > 0 and any(x is not None and x < 0 for x in (mm_change, etf_change, oi_change))
    bullish = price_change is not None and price_change < 0 and any(x is not None and x > 0 for x in (mm_change, etf_change, commercial_change))
    return "BEARISH" if bearish else "BULLISH" if bullish else "NONE"


def _weighted(values: dict, weights: dict) -> tuple[float | None, list[dict]]:
    available = {k: min(100, max(0, values[k])) for k in weights if values.get(k) is not None}
    total = sum(weights[k] for k in available)
    if not total: return None, []
    details = [{"component": k, "normalized_score": v, "weight": weights[k]/total,
                "contribution": v*weights[k]/total, "raw_value": values[k], "reason": "available measured input"} for k,v in available.items()]
    return round(sum(x["contribution"] for x in details), 1), details


def calculate_metals_scores(values: dict, config: dict, asset: str) -> MetalScores:
    cfg = config[asset.lower()]; mm_pct = values.get("mm_percentile")
    divergence = detect_divergence(values.get("price_change"), values.get("mm_change"), values.get("etf_change"), values.get("oi_change"), values.get("commercial_change"))
    demand_inputs = {"mm_trend": values.get("mm_trend_score"), "mm_percentile": mm_pct,
        "etf": values.get("etf_score"), "oi_confirmation": values.get("oi_score"), "commercial": values.get("commercial_score"),
        "divergence": 75 if divergence == "BULLISH" else 25 if divergence == "BEARISH" else 50,
        "trend": values.get("trend_score")}
    demand, details = _weighted(demand_inputs, cfg["demand_weights"])
    risk_inputs = {"mm_net": mm_pct, "mm_long": values.get("mm_long_percentile"), "ma_distance": values.get("ma_risk"),
        "etf_exhaustion": values.get("etf_exhaustion"), "divergence": 80 if divergence == "BEARISH" else 20,
        "oi_extreme": values.get("oi_percentile"), "commercial": values.get("commercial_extreme"), "momentum": values.get("momentum_risk")}
    risk, risk_details = _weighted(risk_inputs, cfg["risk_weights"]); details += risk_details
    drawdown = values.get("drawdown")
    if values.get("price") is None or drawdown is None or drawdown >= 0: dip = None
    else:
        dip_inputs = {"drawdown": 100 if cfg["dip_min"] <= -drawdown <= cfg["dip_max"] else 35,
            "position_reset": values.get("position_reset"), "etf_stability": values.get("etf_score"),
            "oi_reset": values.get("oi_reset"), "commercial_covering": values.get("commercial_score"),
            "long_term_trend": values.get("trend_score"), "reaccumulation": values.get("reaccumulation")}
        dip, dip_details = _weighted(dip_inputs, cfg["dip_weights"]); details += dip_details
        if values.get("above_200dma") is False and (values.get("mm_change") or 0) < 0 and (values.get("etf_change") or 0) < 0 and (values.get("oi_change") or 0) > 0: dip = min(dip or 100, 25)
    required = {"price": values.get("price") is not None, "cftc_mm": values.get("mm_percentile") is not None,
                "open_interest": values.get("open_interest") is not None}
    conf_weights = config.get("confidence_weights", {"price": .20, "cftc_mm": .25, "open_interest": .15,
        "etf": .20, "divergence": .10, "trend": .10})
    available = {**required, "etf": values.get("etf_score") is not None,
        "divergence": values.get("price_change") is not None and values.get("mm_change") is not None,
        "trend": values.get("trend_score") is not None}
    confidence = 100 * sum(w for k,w in conf_weights.items() if available.get(k)) / sum(conf_weights.values())
    minimum_met = all(required.values()) and confidence >= config.get("phase_confidence", 50)
    if not minimum_met: phase = "PARTIAL"
    elif risk is not None and risk >= cfg["phase"]["top_risk"]: phase = "TOP_RISK"
    elif values.get("above_200dma") is False: phase = "DISTRIBUTION" if demand is not None and demand >= 40 else "BEAR"
    elif demand is None: phase = "UNKNOWN"
    elif demand >= cfg["phase"]["late_bull"]: phase = "LATE_BULL"
    elif demand >= cfg["phase"]["mid_bull"]: phase = "MID_BULL"
    elif demand >= cfg["phase"]["early_bull"]: phase = "EARLY_BULL"
    else: phase = "ACCUMULATION"
    confidence -= (15 if values.get("cot_stale") else 0) + (8 if values.get("estimated_flow") else 0)
    return MetalScores(demand, risk, dip, phase, divergence, round(max(0, confidence), 1), details)
