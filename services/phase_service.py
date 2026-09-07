"""One current-phase eligibility rule for the dashboard and downloadable report."""
from dataclasses import dataclass
from datetime import date, datetime, timezone

from indicators.normalization import finite_number
from scoring.regime import PHASE_JA
from services.data_quality import as_date


@dataclass(frozen=True)
class PhaseStatus:
    partial: bool
    stale: bool
    reasons: tuple[str, ...]
    label: str


def phase_status(phase, confidence, day, asset="btc", *, diagnostics=None,
                 as_of: date | None = None) -> PhaseStatus:
    """Recheck a saved phase against its date and currently available inputs.

    A recently saved score may already rely on expired observations. The current
    eligibility is therefore separate from the completeness saved with it.
    ``diagnostics=None`` is supported for inspecting standalone saved snapshots;
    live callers supply diagnostics to validate their underlying data as well.
    """
    as_of = as_date(as_of) or as_date((diagnostics or {}).get("as_of")) or datetime.now(timezone.utc).date()
    snapshot_day = as_date(day)
    age = (as_of - snapshot_day).days if snapshot_day is not None else None
    stale = age is not None and age > 3
    asset = asset.lower()
    eligibility = (diagnostics or {}).get("phase_eligibility", {}).get(asset)
    minimum_confidence = finite_number((eligibility or {}).get("minimum_confidence"))
    minimum_confidence = minimum_confidence if minimum_confidence is not None else 50
    reasons = []
    if age is None or age < 0:
        reasons.append("invalid_snapshot_date")
    elif stale:
        reasons.append("stale_snapshot")
    saved_confidence = finite_number(confidence)
    if saved_confidence is None or saved_confidence < minimum_confidence:
        reasons.append("insufficient_saved_confidence")
    if phase not in PHASE_JA or phase in ("PARTIAL", "UNKNOWN"):
        reasons.append("incomplete_saved_phase")
    if diagnostics is not None:
        sources = diagnostics.get("sources", {})
        required_sources = [f"{asset}_price_usd"]
        if asset != "btc":
            required_sources.append(f"{asset}_cot")
        for name in required_sources:
            if sources.get(name, {}).get("status") != "OK":
                reasons.append(f"unavailable_current_{name}")
        # The health service computes these using the same input builders and
        # minimum-data requirements as the scoring pipeline.
        if eligibility is not None:
            if eligibility.get("minimum_met") is not True:
                reasons.append("insufficient_current_inputs")
            if "confidence" in eligibility:
                current_confidence = finite_number(eligibility["confidence"])
                if current_confidence is None or current_confidence < minimum_confidence:
                    reasons.append("insufficient_current_confidence")
    partial = bool(reasons)
    label = "判定保留 / PARTIAL" if partial else f"{phase} / {PHASE_JA[phase]}"
    return PhaseStatus(partial, stale, tuple(reasons), label)
