"""Transparent, missing-safe institutional-flow scoring for precious metals."""
from dataclasses import dataclass
from datetime import date, timedelta
from statistics import mean, pstdev

from indicators.normalization import finite_number


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
    clean = [number for x in history if (number := finite_number(x)) is not None]
    value = finite_number(value)
    if value is None or len(clean) < minimum:
        return None
    return 100 * sum(x <= value for x in clean) / len(clean)


def zscore(history: list[float], value: float, minimum: int = 20) -> float | None:
    clean = [number for x in history if (number := finite_number(x)) is not None]
    value = finite_number(value)
    if value is None or len(clean) < minimum or not pstdev(clean):
        return None
    return (value - mean(clean)) / pstdev(clean)


def position_statistics(rows: list[dict]) -> dict:
    """Weekly changes use actual report intervals; gaps are never interpolated."""
    rows = sorted({x["report_date"]: x for x in rows}.values(), key=lambda x: x["report_date"])
    if not rows:
        return {}
    latest = rows[-1]
    current = finite_number(latest.get("net"))
    if current is None:
        return {}
    nets = [finite_number(x.get("net")) for x in rows]
    dated = {x["report_date"]: x for x in rows}
    def prior(weeks):
        if isinstance(latest["report_date"], date):
            return dated.get(latest["report_date"] - timedelta(weeks=weeks), {})
        return rows[-1-weeks] if len(rows) > weeks else {}
    def change(weeks):
        old = finite_number(prior(weeks).get("net"))
        return current - old if old is not None else None
    oi = finite_number(latest.get("open_interest"))
    previous_oi = finite_number(prior(1).get("open_interest"))
    long, short = finite_number(latest.get("long")), finite_number(latest.get("short"))
    def window(weeks):
        if isinstance(latest["report_date"], date):
            cutoff = latest["report_date"] - timedelta(weeks=weeks)
            return [finite_number(row.get("net")) for row in rows if row["report_date"] > cutoff]
        return nets[-weeks:]
    return {"long": long, "short": short, "net": current,
            "net_oi": current / oi if oi is not None and oi > 0 else None,
            "long_oi": long / oi if oi is not None and oi > 0 and long is not None else None,
            "short_oi": short / oi if oi is not None and oi > 0 and short is not None else None,
            "change_1w": change(1), "change_4w": change(4), "change_13w": change(13),
            "zscore": zscore(nets, current), "percentile_52w": percentile(window(52), current),
            "percentile_3y": percentile(window(156), current, 52),
            "percentile_full": percentile(nets, current), "open_interest": oi,
            "oi_change_1w": oi - previous_oi if oi is not None and previous_oi is not None else None}


def detect_divergence(price_change, mm_change, etf_change, oi_change, commercial_change) -> str:
    price, mm, etf, oi, commercial = map(finite_number, (price_change, mm_change, etf_change, oi_change, commercial_change))
    if price is None or all(x is None for x in (mm, etf, oi, commercial)):
        return "UNKNOWN"
    bearish = price > 0 and any(x is not None and x < 0 for x in (mm, etf, oi))
    bullish = price < 0 and any(x is not None and x > 0 for x in (mm, etf, commercial))
    return "BEARISH" if bearish else "BULLISH" if bullish else "NONE"


def _weighted(values: dict, weights: dict) -> tuple[float | None, list[dict]]:
    available = {k: min(100, max(0, number)) for k in weights
                 if (number := finite_number(values.get(k))) is not None and weights[k] > 0}
    total = sum(weights[k] for k in available)
    if not total:
        return None, []
    details = [{"component": k, "normalized_score": v, "weight": weights[k] / total,
                "contribution": v * weights[k] / total, "raw_value": values[k],
                "reason": "available measured input"} for k, v in available.items()]
    return round(sum(x["contribution"] for x in details), 1), details


def calculate_metals_scores(values: dict, config: dict, asset: str) -> MetalScores:
    values = {k: v if isinstance(v, bool) or k in {"cot_stale", "estimated_flow", "above_200dma"}
              else finite_number(v) for k, v in values.items()}
    cfg = config[asset.lower()]
    mm_pct = values.get("mm_percentile")
    divergence = detect_divergence(values.get("price_change"), values.get("mm_change"), values.get("etf_change"),
                                   values.get("oi_change"), values.get("commercial_change"))
    has_divergence = divergence != "UNKNOWN"
    demand_inputs = {"mm_trend": values.get("mm_trend_score"), "mm_percentile": mm_pct,
                     "etf": values.get("etf_score"), "oi_confirmation": values.get("oi_score"),
                     "commercial": values.get("commercial_score"),
                     "divergence": (75 if divergence == "BULLISH" else 25 if divergence == "BEARISH" else 50) if has_divergence else None,
                     "trend": values.get("trend_score")}
    demand, details = _weighted(demand_inputs, cfg["demand_weights"])
    risk_inputs = {"mm_net": mm_pct, "mm_long": values.get("mm_long_percentile"), "ma_distance": values.get("ma_risk"),
                   "etf_exhaustion": values.get("etf_exhaustion"),
                   "divergence": (80 if divergence == "BEARISH" else 20) if has_divergence else None,
                   "oi_extreme": values.get("oi_percentile"), "commercial": values.get("commercial_extreme"),
                   "momentum": values.get("momentum_risk")}
    risk, risk_details = _weighted(risk_inputs, cfg["risk_weights"])
    details += risk_details
    drawdown = values.get("drawdown")
    if values.get("price") is None or drawdown is None or drawdown >= 0:
        dip = None
    else:
        dip_inputs = {"drawdown": 100 if cfg["dip_min"] <= -drawdown <= cfg["dip_max"] else 35,
                      "position_reset": values.get("position_reset"), "etf_stability": values.get("etf_score"),
                      "oi_reset": values.get("oi_reset"), "commercial_covering": values.get("commercial_score"),
                      "long_term_trend": values.get("trend_score"), "reaccumulation": values.get("reaccumulation")}
        dip, dip_details = _weighted(dip_inputs, cfg["dip_weights"])
        details += dip_details
        changes = [values.get(k) for k in ("mm_change", "etf_change", "oi_change")]
        if (dip is not None and values.get("above_200dma") is False and all(x is not None for x in changes)
                and changes[0] < 0 and changes[1] < 0 and changes[2] > 0):
            dip = min(dip, 25)
    required = {"price": values.get("price") is not None,
                "cftc_mm": mm_pct is not None and not values.get("cot_stale"),
                "open_interest": values.get("open_interest") is not None and not values.get("cot_stale")}
    conf_weights = config.get("confidence_weights", {"price": .20, "cftc_mm": .25, "open_interest": .15,
                                                      "etf": .20, "divergence": .10, "trend": .10})
    available = {**required, "etf": values.get("etf_score") is not None,
                 "divergence": has_divergence, "trend": values.get("trend_score") is not None}
    total_weight = sum(conf_weights.values())
    confidence = 100 * sum(w for k, w in conf_weights.items() if available.get(k)) / total_weight if total_weight else 0
    confidence -= 8 if values.get("estimated_flow") else 0
    confidence = round(max(0, confidence), 1)
    minimum_met = all(required.values()) and confidence >= config.get("phase_confidence", 50)
    if not minimum_met:
        phase = "PARTIAL"
    elif risk is not None and risk >= cfg["phase"]["top_risk"]:
        phase = "TOP_RISK"
    elif values.get("above_200dma") is False:
        phase = "DISTRIBUTION" if demand is not None and demand >= 40 else "BEAR"
    elif demand is None:
        phase = "UNKNOWN"
    elif demand >= cfg["phase"]["late_bull"]:
        phase = "LATE_BULL"
    elif demand >= cfg["phase"]["mid_bull"]:
        phase = "MID_BULL"
    elif demand >= cfg["phase"]["early_bull"]:
        phase = "EARLY_BULL"
    else:
        phase = "ACCUMULATION"
    return MetalScores(demand, risk, dip, phase, divergence, confidence, details)
