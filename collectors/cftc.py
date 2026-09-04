"""Official CFTC public-data collector for weekly disaggregated futures-only COT."""
from datetime import date, datetime, timezone
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


def _number(row: dict[str, Any], field: str | None) -> float | None:
    if not field or row.get(field) in (None, ""): return None
    try: return float(str(row[field]).replace(",", ""))
    except (TypeError, ValueError): return None


class CFTCCollector(HTTPCollector):
    """Gold/Silver COT; report_date is Tuesday's weekly effective date."""
    def __init__(self, asset: str, **kwargs):
        asset = asset.lower()
        if asset not in CONTRACTS: raise ValueError("asset must be gold or silver")
        super().__init__(**kwargs); self.asset = asset

    def fetch_history(self, start_date: date, end_date: date) -> list[dict]:
        where = (f"cftc_contract_market_code='{CONTRACTS[self.asset]}' AND "
                 f"report_date_as_yyyy_mm_dd between '{start_date.isoformat()}T00:00:00.000' "
                 f"and '{end_date.isoformat()}T23:59:59.999'")
        rows = self._get_json(CFTC_DATASET, params={"$where": where, "$order": "report_date_as_yyyy_mm_dd", "$limit": 5000})
        fetched = datetime.now(timezone.utc); result = []
        for row in rows:
            report_date = date.fromisoformat(row["report_date_as_yyyy_mm_dd"][:10])
            oi = _number(row, "open_interest_all")
            for category, (long_key, short_key, spreading_key) in CATEGORIES.items():
                long, short = _number(row, long_key), _number(row, short_key)
                result.append({"asset": self.asset.upper(), "report_date": report_date, "category": category,
                    "long": long, "short": short, "spreading": _number(row, spreading_key),
                    "net": long - short if long is not None and short is not None else None,
                    "open_interest": oi, "source": CFTC_DATASET, "fetched_at": fetched, "status": "OK"})
        return result

    def fetch_latest(self) -> list[dict]:
        today = datetime.now(timezone.utc).date()
        return self.fetch_history(today.replace(year=today.year - 1), today)[-len(CATEGORIES):]
