"""Parse official GLD, IAU and SLV sponsor downloads without fixed offsets."""
import csv
import io
import json
import logging
import re
from datetime import date, datetime, timezone

from collectors.base import HTTPCollector

logger = logging.getLogger(__name__)

FUNDS = {
    "GLD": ("GOLD", "https://www.spdrgoldshares.com/assets/dynamic/GLD/GLD_US_archive_EN.csv"),
    "IAU": ("GOLD", "https://www.ishares.com/us/products/239561/ishares-gold-trust-fund/1467271812596.ajax?fileType=csv&fileName=IAU_holdings&dataType=fund"),
    "SLV": ("SILVER", "https://www.ishares.com/us/products/239855/ishares-silver-trust-fund/1467271812596.ajax?fileType=csv&fileName=SLV_holdings&dataType=fund"),
}


def _norm(value):
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(value).lower()).split())


def _num(value):
    """Parse sponsor-formatted numbers, while never converting missing data to zero."""
    if value is None:
        return None
    text = str(value).strip().strip('"').replace("\u00a0", " ")
    if text.lower() in ("", "-", "--", "n/a", "na", "not available"):
        return None
    negative = text.startswith("(") and text.endswith(")")
    text = text.removeprefix("(").removesuffix(")").strip()
    # Only known decoration may surround the number.  This prevents accidentally
    # interpreting dates, identifiers, or arbitrary prose as holdings.
    match = re.fullmatch(r"(?:[$£€]\s*)?([+-]?[\d,]+(?:\.\d+)?)\s*(?:%|oz|ounces?|tonnes?|tons?)?", text, re.I)
    if not match:
        return None
    try:
        number = float(match.group(1).replace(",", ""))
        return -number if negative else number
    except ValueError:
        return None


def _date(value):
    value = str(value or "").strip().strip('"')
    value = re.sub(r"^(?:as\s+of|holdings\s+as\s+of)\s+", "", value, flags=re.I)
    for fmt in ("%d-%b-%Y", "%d-%b-%y", "%Y-%m-%d", "%b %d, %Y", "%B %d, %Y", "%b %d %Y", "%B %d %Y",
                "%m/%d/%Y", "%m/%d/%y", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    return None


def _matching(values, aliases):
    """Pick an unambiguous semantic field; aliases are exact normalized names."""
    normalized_aliases = {_norm(alias) for alias in aliases}
    for key, value in values.items():
        if _norm(key) in normalized_aliases:
            parsed = _num(value)
            if parsed is not None:
                return parsed
    return None


def _pairs(rows):
    """Return metadata from both ``key,value`` and ``header/value`` CSV blocks."""
    result = {}
    for row in rows:
        cells = [cell.strip() for cell in row]
        if len(cells) >= 2 and cells[0]:
            result.setdefault(cells[0], cells[1])
    # Current iShares downloads contain a conventional field-name row followed
    # by its values in parts of the preamble.  Do not confuse the holdings table
    # with metadata: only recognised summary labels are promoted.
    summary = {"shares outstanding", "net assets", "net assets of fund",
               "ounces in trust", "tonnes in trust", "fund holdings as of",
               "holdings as of", "as of"}
    for header, values in zip(rows, rows[1:]):
        normalized = [_norm(cell) for cell in header]
        if len(values) == len(header) and sum(name in summary for name in normalized):
            for key, value in zip(header, values):
                if _norm(key) in summary and str(value).strip():
                    result.setdefault(str(key).strip(), str(value).strip())
    return result


class MetalsETFCollector(HTTPCollector):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.diagnostics: dict[str, dict] = {}

    @staticmethod
    def _decode(response) -> str:
        raw = response.content
        for encoding in ("utf-8-sig", "utf-16", "latin-1"):
            try:
                return raw.decode(encoding)
            except (UnicodeDecodeError, UnicodeError):
                continue
        return response.text

    def _diagnostic_record(self, fund, asset, source, fetched, status, error):
        # ``date`` is the storage/upsert partition, not an asserted sponsor date.
        # effective_date intentionally remains NULL when the sponsor did not supply one.
        return {"asset": asset, "fund": fund, "date": fetched.date(), "effective_date": None,
                "shares_outstanding": None, "ounces": None, "tonnes": None, "nav": None,
                "physical_holdings": None, "holdings_unit": None, "net_assets": None,
                "flow": None, "flow_status": "UNAVAILABLE", "source": source,
                "fetched_at": fetched, "published_at": None, "status": status,
                "error": str(error)[:500]}

    @staticmethod
    def _shape(content):
        """Build a bounded, non-sensitive schema description for field logs."""
        try:
            value = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            rows = list(csv.reader(io.StringIO(content.lstrip("\ufeff").replace("\x00", ""))))
            keywords = ("shares outstanding", "net assets", "ounces", "tonnes",
                        "fund holdings", "holdings", "as of")
            candidates = []
            for number, row in enumerate(rows[:40], 1):
                normalized_row = _norm(" ".join(row))
                # Schema only: values (including dollar amounts and dates) never
                # enter diagnostics. In key/value rows only the key is a field.
                possible_headers = row[:1] if len(row) == 2 else row[:6]
                names = [_norm(cell)[:60] for cell in possible_headers
                         if re.search(r"[A-Za-z]", str(cell)) and _num(cell) is None and _date(cell) is None]
                if number <= 5 or any(word in normalized_row for word in keywords):
                    candidates.append({"line": number, "columns": len(row), "fields": names})
            return {"type": "CSV", "row_count": len(rows), "candidate_rows": candidates[:15]}
        items = value if isinstance(value, list) else next(
            (v for v in value.values() if isinstance(v, list)), []) if isinstance(value, dict) else []
        top = sorted(map(str, value.keys()))[:30] if isinstance(value, dict) else []
        keys = lambda item: sorted(map(str, item.keys()))[:30] if isinstance(item, dict) else []
        all_keys = {_norm(k) for item in items[:100] if isinstance(item, dict) for k in item}
        return {"type": "JSON", "top_level_keys": top, "row_count": len(items),
                "first_item_keys": keys(items[0]) if items else [],
                "last_item_keys": keys(items[-1]) if items else [],
                "weight_fields": sorted(k for k in all_keys if "weight" in k or "ounce" in k or "tonne" in k),
                "date_fields": sorted(k for k in all_keys if "date" in k)}

    def fetch_history(self, start_date: date, end_date: date) -> list[dict]:
        records = []
        self.diagnostics = {}
        for fund, (asset, url) in FUNDS.items():
            fetched = datetime.now(timezone.utc)
            diag = {"http_status": None, "raw_count": 0, "parsed_count": 0,
                    "normalized_count": 0, "status": "HTTP_ERROR"}
            try:
                response = self.client.get(url, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"})
                diag["http_status"] = response.status_code
                response.raise_for_status()
                content = self._decode(response)
                shape = self._shape(content)
                diag["schema"] = shape
                diag["raw_count"] = shape["row_count"]
                logger.info("%s response schema=%s", fund, shape)
                parsed = self._parse(fund, asset, url, content, start_date, end_date, fetched=fetched)
                diag["parsed_count"] = len(parsed)
                diag["normalized_count"] = len(parsed)
                if parsed:
                    diag["status"] = "HTTP_OK_PARSE_OK"
                    records.extend(parsed)
                else:
                    is_markup = bool(re.search(r"<!doctype\s+html|<html", content[:1000], re.I))
                    normalized_content = _norm(content[:10000])
                    known_schema = any(marker in normalized_content for marker in
                                       ("shares outstanding", "fund holdings as of", "total gold in trust", "ounces in trust"))
                    unexpected = is_markup or (diag["raw_count"] > 0 and not known_schema)
                    diag["status"] = "HTTP_OK_SCHEMA_UNEXPECTED" if unexpected else "HTTP_OK_PARSE_EMPTY"
            except Exception as exc:
                diag["error"] = type(exc).__name__
            self.diagnostics[fund] = diag
            logger.info("%s HTTP=%s raw rows=%d parsed rows=%d normalized records=%d status=%s",
                        fund, diag["http_status"], diag["raw_count"], diag["parsed_count"],
                        diag["normalized_count"], diag["status"])
        return records

    def _record(self, fund, asset, source, day, fetched, values):
        shares = _matching(values, ("shares outstanding", "shares outstanding as of", "shares outstanding end of day"))
        ounces = _matching(values, ("total gold in trust in ounces", "total silver in trust in ounces",
                           "total ounces", "ounces in trust", "ounces", "fine ounces"))
        tonnes = _matching(values, ("total gold in trust in tonnes", "total silver in trust in tonnes",
                           "tonnes in trust", "tonnes", "metric tonnes"))
        nav = _matching(values, ("total net asset value in the trust", "total net assets", "net assets",
                        "net assets of fund", "market value"))
        if all(v is None for v in (shares, ounces, tonnes, nav)):
            return None
        physical, unit = (ounces, "OUNCES") if ounces is not None else ((tonnes, "TONNES") if tonnes is not None else (None, None))
        published_value = next((v for k, v in values.items() if _norm(k) in ("published at", "publication date")), None)
        published_day = _date(published_value)
        return {"asset": asset, "fund": fund, "date": day or fetched.date(), "effective_date": day,
                "shares_outstanding": shares, "ounces": ounces, "tonnes": tonnes, "nav": nav,
                "physical_holdings": physical, "holdings_unit": unit, "net_assets": nav,
                "flow": None, "flow_status": "UNAVAILABLE", "source": source, "fetched_at": fetched,
                "published_at": datetime.combine(published_day, datetime.min.time(), tzinfo=timezone.utc) if published_day else None,
                "status": "OK", "error": None}

    def _parse(self, fund, asset, source, content, start_date, end_date, fetched=None):
        fetched = fetched or datetime.now(timezone.utc)
        try:
            payload = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            payload = None
        if payload is not None:
            record = self._parse_json_summary(fund, asset, source, payload, fetched)
            return [record] if record else []
        rows = list(csv.reader(io.StringIO(content.lstrip("\ufeff").replace("\x00", ""))))
        result = []

        # GLD archive: detect the semantic header rather than assuming its line number.
        header_idx = next((i for i, row in enumerate(rows)
                           if any(_norm(c) in ("date", "effective date") for c in row)), None)
        if header_idx is not None:
            headers = [c.strip() for c in rows[header_idx]]
            date_key = next((h for h in headers if _norm(h) in ("date", "effective date")), None)
            for row in rows[header_idx + 1:]:
                values = dict(zip(headers, row))
                day = _date(values.get(date_key)) if date_key else None
                if day and start_date <= day <= end_date:
                    record = self._record(fund, asset, source, day, fetched, values)
                    if record:
                        result.append(record)
        if result:
            return result

        # iShares has metadata before its actual holdings header. Both can move.
        pairs = _pairs(rows)
        asof_value = next((v for k, v in pairs.items() if _norm(k) in
                          ("fund holdings as of", "holdings as of", "as of", "as of date", "effective date")), None)
        day = _date(asof_value)
        if day and not start_date <= day <= end_date:
            return []
        values = dict(pairs)
        holdings_header = next((i for i, row in enumerate(rows)
                                if "quantity" in {_norm(c) for c in row} and
                                ({"name", "asset class", "ticker"} & {_norm(c) for c in row})), None)
        if holdings_header is not None:
            headers = [_norm(c) for c in rows[holdings_header]]
            candidates = []
            for row in rows[holdings_header + 1:]:
                item = dict(zip(headers, row))
                identity = " ".join((item.get("ticker", ""), item.get("name", ""), item.get("asset class", ""))).lower()
                metal = "gold" if asset == "GOLD" else "silver"
                if metal in identity or item.get("ticker", "").upper() in ({"XAU", "GOLD"} if asset == "GOLD" else {"XAG", "SLV"}):
                    quantity = _num(item.get("quantity"))
                    if quantity is not None:
                        candidates.append((quantity, item))
            # Never sum a bar list: only a single commodity holding is unambiguous.
            if len(candidates) == 1:
                quantity, item = candidates[0]
                values["ounces"] = quantity
                market_value = _num(item.get("market value"))
                if market_value is not None and _matching(values, ("total net assets", "net assets", "net assets of fund")) is None:
                    values["net assets"] = market_value
        record = self._record(fund, asset, source, day, fetched, values)
        return [record] if record else []

    def _parse_json_summary(self, fund, asset, source, payload, fetched):
        """Parse an explicit sponsor summary; deliberately never sum bar rows."""
        objects = []
        def visit(value, depth=0):
            if depth > 4:
                return
            if isinstance(value, dict):
                objects.append(value)
                for child in value.values():
                    visit(child, depth + 1)
            elif isinstance(value, list):
                for child in value:
                    visit(child, depth + 1)
        visit(payload)
        for values in objects:
            normalized = {_norm(key): value for key, value in values.items()}
            day_value = next((value for key, value in normalized.items()
                              if key in ("date", "effective date", "as of", "holdings as of")), None)
            day = _date(day_value)
            record = self._record(fund, asset, source, day, fetched, values)
            if record:
                return record
        return None

    def fetch_latest(self) -> list[dict]:
        today = datetime.now(timezone.utc).date()
        return self.fetch_history(today.replace(year=today.year - 1), today)
