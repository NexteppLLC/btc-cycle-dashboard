"""Config-driven cycle progression score with missing-data reweighting."""
from dataclasses import dataclass

from indicators.normalization import minmax


@dataclass
class ScoreResult:
    score: float | None
    coverage: float
    details: list[dict]


def calculate_cycle_score(values: dict[str, float | None], config: dict) -> ScoreResult:
    weights, ranges = config["weights"], config["ranges"]
    normalized = {name: (values.get(name) if name in {"lth_distribution", "sth_state"} else minmax(values.get(name), *ranges[name])) for name in weights}
    present = {name: score for name, score in normalized.items() if score is not None}
    coverage = sum(weights[name] for name in present)
    if not present: return ScoreResult(None, 0, [])
    details = []
    for name, score in present.items():
        effective = weights[name] / coverage
        details.append({"component": name, "raw_value": values.get(name), "normalized_score": round(score, 2), "weight": weights[name], "contribution": round(score * effective, 2), "reason": f"設定範囲と履歴特性に対する正規化（欠損時再ウェイト {effective:.1%}）"})
    return ScoreResult(round(sum(x["contribution"] for x in details), 2), round(coverage, 2), details)
