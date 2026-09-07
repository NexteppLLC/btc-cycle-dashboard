"""Config-driven cycle progression score with missing-data reweighting."""
from dataclasses import dataclass

from indicators.normalization import finite_number, minmax


@dataclass
class ScoreResult:
    score: float | None
    coverage: float
    details: list[dict]


def calculate_cycle_score(values: dict[str, float | None], config: dict) -> ScoreResult:
    weights = {name: weight for name, raw in config["weights"].items()
               if (weight := finite_number(raw)) is not None and weight > 0}
    ranges = config["ranges"]
    normalized = {
        name: minmax(values.get(name), *((0, 100) if name in {"lth_distribution", "sth_state"} else ranges[name]))
        for name in weights
    }
    present = {name: score for name, score in normalized.items() if score is not None}
    coverage = sum(weights[name] for name in present)
    if not present or finite_number(coverage) is None: return ScoreResult(None, 0, [])
    details = []
    for name, score in present.items():
        effective = weights[name] / coverage
        details.append({"component": name, "raw_value": finite_number(values.get(name)), "normalized_score": round(score, 2), "weight": weights[name], "contribution": round(score * effective, 2), "reason": f"設定範囲と履歴特性に対する正規化（欠損時再ウェイト {effective:.1%}）"})
    score = round(sum(score * (weights[name] / coverage) for name, score in present.items()), 2)
    return ScoreResult(min(100.0, max(0.0, score)), round(coverage, 2), details)
