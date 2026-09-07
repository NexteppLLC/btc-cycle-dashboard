"""Top proximity risk distinct from market direction."""
from indicators.normalization import finite_number, minmax
from .cycle_score import ScoreResult


def calculate_top_risk(values: dict[str, float | None], config: dict) -> ScoreResult:
    weights = {name: weight for name, raw in config["weights"].items()
               if (weight := finite_number(raw)) is not None and weight > 0}
    scores = {
        "lth_mvrv": minmax(values.get("lth_mvrv"), 1.5, 5),
        "mvrv_zscore": minmax(values.get("mvrv_zscore"), 1, 8),
        "lth_sopr": minmax(values.get("lth_sopr"), 1, 2),
        "lth_distribution": minmax(values.get("lth_distribution"), 0, 100),
        "sth_mvrv": minmax(values.get("sth_mvrv"), 1, 2),
        "etf_divergence": minmax(values.get("etf_divergence"), 0, 100),
        "trend_deviation": minmax(values.get("trend_deviation"), .1, 1),
    }
    present = {k: v for k, v in scores.items() if v is not None and k in weights}; coverage = sum(weights[k] for k in present)
    if not present or finite_number(coverage) is None: return ScoreResult(None, 0, [])
    details = [{"component": f"top_{k}", "raw_value": finite_number(values.get(k)), "normalized_score": round(v, 2), "weight": weights[k], "contribution": round(v * (weights[k] / coverage), 2), "reason": "天井リスク複合要因（欠損時再ウェイト）"} for k, v in present.items()]
    # Sum unrounded inputs: rounding every contribution can turn an exact boundary
    # (notably 100) into 99.99.  Clamp after the final rounding for numerical safety.
    score = round(sum(scores[k] * (weights[k] / coverage) for k in present), 2)
    score = min(100.0, max(0.0, score))
    return ScoreResult(score, round(coverage, 2), details)


def risk_label(score: float | None) -> str:
    score = finite_number(score)
    if score is None: return "判定不能"
    for limit, label in ((30, "Low"), (50, "Normal"), (70, "Caution"), (80, "High"), (90, "Very High")): 
        if score < limit: return label
    return "Extreme"
