"""Top proximity risk distinct from market direction."""
from indicators.normalization import minmax
from .cycle_score import ScoreResult


def calculate_top_risk(values: dict[str, float | None], config: dict) -> ScoreResult:
    weights = config["weights"]
    scores = {
        "lth_mvrv": minmax(values.get("lth_mvrv"), 1.5, 5),
        "mvrv_zscore": minmax(values.get("mvrv_zscore"), 1, 8),
        "lth_sopr": minmax(values.get("lth_sopr"), 1, 2),
        "lth_distribution": values.get("lth_distribution"),
        "sth_mvrv": minmax(values.get("sth_mvrv"), 1, 2),
        "etf_divergence": values.get("etf_divergence"),
        "trend_deviation": minmax(values.get("trend_deviation"), .1, 1),
    }
    present = {k: v for k, v in scores.items() if v is not None}; coverage = sum(weights[k] for k in present)
    if not present: return ScoreResult(None, 0, [])
    details = [{"component": f"top_{k}", "raw_value": values.get(k), "normalized_score": round(v, 2), "weight": weights[k], "contribution": round(v * weights[k] / coverage, 2), "reason": "天井リスク複合要因（欠損時再ウェイト）"} for k, v in present.items()]
    return ScoreResult(round(sum(x["contribution"] for x in details), 2), round(coverage, 2), details)


def risk_label(score: float | None) -> str:
    if score is None: return "判定不能"
    for limit, label in ((30, "Low"), (50, "Normal"), (70, "Caution"), (80, "High"), (90, "Very High")): 
        if score < limit: return label
    return "Extreme"

