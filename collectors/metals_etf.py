"""Official sponsor-published holdings for GLD, IAU and SLV.

Sponsor files change layout occasionally, therefore parsing is deliberately
defensive: fields that cannot be identified remain ``None`` rather than being
invented.  ``flow`` is an explicitly labelled estimate from day-over-day NAV.
"""
import csv
import io
import re
from datetime import date, datetime, timezone

from collectors.base import HTTPCollector

FUNDS = {
    "GLD": ("GOLD", "https://www.spdrgoldshares.com/assets/dynamic/GLD/GLD_US_archive_EN.csv"),
    "IAU": ("GOLD", "https://www.ishares.com/us/products/239561/ishares-gold-trust-fund/1467271812596.ajax?fileType=csv&fileName=IAU_holdings&dataType=fund"),
    "SLV": ("SILVER", "https://www.ishares.com/us/products/239855/ishares-silver-trust-fund/1467271812596.ajax?fileType=csv&fileName=SLV_holdings&dataType=fund"),
}


def _num(value):
    if value is None:
        return None
    value = re.sub(r"[$,\"]", "", str(value)).strip()
    try:
        return float(value) if value not in ("", "-", "N/A") else None
    except ValueError:
        return None


class MetalsETFCollector(HTTPCollector):
    """Collect fund-level values only when present in an official sponsor CSV."""

    def fetch_history(self, start_date: date, end_date: date) -> list[dict]:
        records = []
        for fund, (asset, url) in FUNDS.items():
            try:
                response = self.client.get(url, follow_redirects=True); response.raise_for_status()
                records.extend(self._parse(fund, asset, url, response.text, start_date, end_date))
            except Exception:
                continue
        return records

    def _parse(self, fund, asset, source, content, start_date, end_date):
        fetched = datetime.now(timezone.utc); result = []
        rows = list(csv.reader(io.StringIO(content.lstrip("\ufeff"))))
        # SPDR archive is a conventional dated table; iShares metadata is
        # key/value oriented.  Match semantic column names instead of offsets.
        header_idx = next((i for i, row in enumerate(rows) if any("date" in c.lower() for c in row)), None)
        if header_idx is not None:
            headers = [c.strip().lower() for c in rows[header_idx]]
            for row in rows[header_idx + 1:]:
                values = dict(zip(headers, row))
                raw_date = next((v for k, v in values.items() if "date" in k), None)
                try: day = datetime.strptime(raw_date.strip(), "%d-%b-%Y").date()
                except (AttributeError, ValueError):
                    try: day = datetime.fromisoformat(raw_date.strip()).date()
                    except (AttributeError, ValueError): continue
                if not start_date <= day <= end_date: continue
                pick = lambda words: _num(next((v for k,v in values.items() if all(w in k for w in words)), None))
                result.append({"asset": asset, "fund": fund, "date": day,
                    "shares_outstanding": pick(("shares", "outstanding")), "ounces": pick(("ounces",)),
                    "tonnes": pick(("tonnes",)), "nav": pick(("nav",)), "flow": None,
                    "flow_status": "N/A", "source": source, "fetched_at": fetched, "status": "OK"})
        if result:
            return result
        # Current iShares files expose fund statistics before their holdings table.
        pairs = {row[0].strip().lower(): row[1] for row in rows if len(row) >= 2}
        asof = next((v for k,v in pairs.items() if "as of" in k), None)
        day = None
        for fmt in ("%b %d, %Y", "%d-%b-%Y", "%Y-%m-%d"):
            try: day = datetime.strptime(asof.strip(), fmt).date(); break
            except (AttributeError, ValueError): pass
        if day and start_date <= day <= end_date:
            find = lambda phrase: _num(next((v for k,v in pairs.items() if phrase in k), None))
            result.append({"asset": asset, "fund": fund, "date": day,
                "shares_outstanding": find("shares outstanding"), "ounces": find("ounces"),
                "tonnes": find("tonnes"), "nav": find("net assets"), "flow": None,
                "flow_status": "N/A", "source": source, "fetched_at": fetched, "status": "OK"})
        return result

    def fetch_latest(self) -> list[dict]:
        today = datetime.now(timezone.utc).date()
        return self.fetch_history(today.replace(year=today.year - 1), today)
