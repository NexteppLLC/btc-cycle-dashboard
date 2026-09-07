"""Official CFTC public-data collector for weekly disaggregated futures-only COT."""
from datetime import date, datetime, timedelta, timezone
import math
from typing import Any

from collectors.base import HTTPCollector

CFTC_DATASET = "https://publicreporting.cftc.gov/resource/72hh-3qpy.json"
CONTRACTS = {"gold": "088691", "silver": "084691"}
CATEGORIES = {
    "producer_merchant": ("prod_merc_positions_long", "prod_merc_positions_short", None),
    "swap_dealer": ("swap_positions_long_all", "swap__positions_short_all", "swap__positions_spread_all"),
    "managed_money": ("m_money_positions_long_all", "m_money_positions_short_all", "m_money_positions_spread"),
    "other_reportable": ("other_rept_positions_long", "other_rept_positions_short", "other_rept_positions_spread"),
    "nonreportable": ("nonrept_positions_long_all", "nonrept_positions_short_all", None),
}


def scheduled_publication_date(position_date: date) -> date:
    """Normal Friday publication for Tuesday positions; holiday delays excluded."""
    return position_date + timedelta(days=3)


def _number(row: dict[str, Any], field: str | None) -> float | None:
    if not field or row.get(field) in (None, ""): return None
    try:
        value = float(str(row[field]).replace(",", ""))
        return value if math.isfinite(value) and value >= 0 else None
    except (TypeError, ValueError): return None


class CFTCCollector(HTTPCollector):
    """Gold/Silver COT; report_date is Tuesday's weekly effective date."""
    def __init__(self, asset: str, **kwargs):
        asset = asset.lower()
        if asset not in CONTRACTS: raise ValueError("asset must be gold or silver")
        super().__init__(**kwargs); self.asset = asset

    def fetch_history(self, start_date: date, end_date: date) -> list[dict]:
        if start_date > end_date:
            return []
        where = (f"cftc_contract_market_code='{CONTRACTS[self.asset]}' AND "
                 f"report_date_as_yyyy_mm_dd between '{start_date.isoformat()}T00:00:00.000' "
                 f"and '{end_date.isoformat()}T23:59:59.999'")
        rows = self._get_json(CFTC_DATASET, params={"$where": where, "$order": "report_date_as_yyyy_mm_dd", "$limit": 5000})
        if not isinstance(rows, list):
            raise ValueError("CFTC response is not a positions table")
        fetched = datetime.now(timezone.utc); result = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                report_date = date.fromisoformat(str(row.get("report_date_as_yyyy_mm_dd", ""))[:10])
            except ValueError:
                continue
            if not start_date <= report_date <= end_date:
                continue
            contract = row.get("cftc_contract_market_code")
            if contract is not None and str(contract).zfill(6) != CONTRACTS[self.asset]:
                continue
            oi = _number(row, "open_interest_all")
            for category, (long_key, short_key, spreading_key) in CATEGORIES.items():
                long, short = _number(row, long_key), _number(row, short_key)
                result.append({"asset": self.asset.upper(), "report_date": report_date, "category": category,
                    "long": long, "short": short, "spreading": _number(row, spreading_key),
                    "net": long - short if long is not None and short is not None else None,
                    "open_interest": oi, "source": CFTC_DATASET, "fetched_at": fetched,
                    "status": "OK" if long is not None and short is not None else "MISSING"})
        unique = {(r["report_date"], r["category"]): r for r in result}
        return [unique[key] for key in sorted(unique)]

    def fetch_latest(self) -> list[dict]:
        today = datetime.now(timezone.utc).date()
        return self.fetch_history(today - timedelta(days=366), today)[-len(CATEGORIES):]
