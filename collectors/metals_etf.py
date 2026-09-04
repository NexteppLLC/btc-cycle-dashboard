"""Parse official GLD, IAU and SLV sponsor downloads without fixed offsets."""
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


def _norm(value):
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(value).lower()).split())


def _num(value):
    if value is None:
        return None
    cleaned = re.sub(r"[$,%\s,\"]", "", str(value)).replace("(", "-").replace(")", "")
    try:
        return float(cleaned) if cleaned.lower() not in ("", "-", "n/a", "na") else None
    except ValueError:
        return None


def _date(value):
    value = str(value or "").strip().strip('"')
    for fmt in ("%d-%b-%Y", "%Y-%m-%d", "%b %d, %Y", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    return None


def _matching(values, aliases):
    """Pick an unambiguous semantic field; aliases are exact normalized names."""
    for alias in aliases:
        matches = [value for key, value in values.items() if _norm(key) == alias]
        if len(matches) == 1:
            return _num(matches[0])
    return None


class MetalsETFCollector(HTTPCollector):
    def fetch_history(self, start_date: date, end_date: date) -> list[dict]:
        records = []
        for fund, (asset, url) in FUNDS.items():
            try:
                response = self.client.get(url, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"})
                response.raise_for_status()
                records.extend(self._parse(fund, asset, url, response.text, start_date, end_date))
            except Exception:
                # Providers are fault-isolated. No synthetic row/value is emitted.
                continue
        return records

    def _record(self, fund, asset, source, day, fetched, values):
        shares = _matching(values, ("shares outstanding", "shares outstanding as of"))
        ounces = _matching(values, ("total gold in trust in ounces", "total ounces", "ounces in trust", "ounces"))
        tonnes = _matching(values, ("total gold in trust in tonnes", "total silver in trust in tonnes", "tonnes in trust", "tonnes"))
        nav = _matching(values, ("total net asset value in the trust", "total net assets", "net assets"))
        if all(v is None for v in (shares, ounces, tonnes, nav)):
            return None
        physical, unit = (ounces, "OUNCES") if ounces is not None else ((tonnes, "TONNES") if tonnes is not None else (None, None))
        published_value = next((v for k, v in values.items() if _norm(k) in ("published at", "publication date")), None)
        published_day = _date(published_value)
        return {"asset": asset, "fund": fund, "date": day, "effective_date": day,
                "shares_outstanding": shares, "ounces": ounces, "tonnes": tonnes, "nav": nav,
                "physical_holdings": physical, "holdings_unit": unit, "net_assets": nav,
                "flow": None, "flow_status": "UNAVAILABLE", "source": source, "fetched_at": fetched,
                "published_at": datetime.combine(published_day, datetime.min.time(), tzinfo=timezone.utc) if published_day else None,
                "status": "OK", "error": None}

    def _parse(self, fund, asset, source, content, start_date, end_date):
        fetched = datetime.now(timezone.utc)
        rows = list(csv.reader(io.StringIO(content.lstrip("\ufeff").replace("\x00", ""))))
        result = []

        # GLD archive: locate a real daily Date column, then map normalized names.
        header_idx = next((i for i, row in enumerate(rows) if any(_norm(c) in ("date", "effective date") for c in row)), None)
        if header_idx is not None:
            headers = [c.strip() for c in rows[header_idx]]
            date_keys = [h for h in headers if _norm(h) in ("date", "effective date")]
            for row in rows[header_idx + 1:]:
                values = dict(zip(headers, row))
                day = _date(values.get(date_keys[0])) if date_keys else None
                if day and start_date <= day <= end_date:
                    record = self._record(fund, asset, source, day, fetched, values)
                    if record:
                        result.append(record)
        if result:
            return result

        # iShares starts with key/value fund statistics and then a holdings table.
        pairs = {row[0].strip(): row[1].strip() for row in rows if len(row) >= 2 and row[0].strip()}
        asof_value = next((v for k, v in pairs.items() if _norm(k) in
                           ("fund holdings as of", "holdings as of", "as of date", "effective date")), None)
        day = _date(asof_value)
        if not day or not start_date <= day <= end_date:
            return []
        values = dict(pairs)

        # Commodity trusts expose the measured metal as Quantity in their holdings table.
        holdings_header = next((i for i, row in enumerate(rows)
                                if "quantity" in {_norm(c) for c in row} and
                                ("name" in {_norm(c) for c in row} or "asset class" in {_norm(c) for c in row})), None)
        if holdings_header is not None:
            headers = [_norm(c) for c in rows[holdings_header]]
            for row in rows[holdings_header + 1:]:
                item = dict(zip(headers, row))
                identity = " ".join((item.get("ticker", ""), item.get("name", ""), item.get("asset class", ""))).lower()
                metal = "gold" if asset == "GOLD" else "silver"
                if metal in identity:
                    quantity = _num(item.get("quantity"))
                    if quantity is not None:
                        values["ounces"] = quantity  # sponsor commodity-trust quantity is ounces
                    market_value = _num(item.get("market value"))
                    if market_value is not None and _matching(values, ("total net assets", "net assets")) is None:
                        values["net assets"] = market_value
                    break
        record = self._record(fund, asset, source, day, fetched, values)
        return [record] if record else []

    def fetch_latest(self) -> list[dict]:
        today = datetime.now(timezone.utc).date()
        return self.fetch_history(today.replace(year=today.year - 1), today)
