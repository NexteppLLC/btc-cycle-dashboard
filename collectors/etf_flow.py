"""ETF flow ingestion from an operator-approved structured CSV feed.

No brittle HTML scraping is performed. Without a configured URL the state is
PENDING rather than zero or a copied prior value.

Each UTC date produces one aggregate. A unique explicit ``fund=TOTAL`` row is
authoritative and is never added to its component funds. Otherwise every named
fund observed in the feed must have one finite value on that date; omitted or
missing constituents make the total unavailable. Unlabelled duplicate rows and
duplicate fund/TOTAL rows are ambiguous and are rejected, even if values match.
"""
from datetime import date, datetime, timezone
from io import StringIO
from math import fsum, isfinite

import pandas as pd

from .base import HTTPCollector, MetricPoint, MetricStatus, unavailable


class ETFFlowCollector(HTTPCollector):
    def __init__(self, csv_url: str | None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.csv_url = csv_url

    @staticmethod
    def _daily_total(rows, expected_funds):
        totals = rows[rows["fund"] == "TOTAL"]
        if len(totals) > 1:
            return None, MetricStatus.ERROR, "Duplicate TOTAL rows"
        if len(totals) == 1:
            selected = totals
        elif rows["fund"].isna().any():
            if len(rows) != 1 or expected_funds:
                return None, MetricStatus.ERROR, "Ambiguous unlabelled fund rows"
            selected = rows
        elif rows["fund"].duplicated().any():
            return None, MetricStatus.ERROR, "Duplicate constituent fund rows"
        elif set(rows["fund"]) != expected_funds:
            return None, MetricStatus.MISSING, "Missing constituent fund rows"
        else:
            selected = rows

        values = pd.to_numeric(selected["flow_usd"], errors="coerce")
        if any(pd.isna(value) or not isfinite(float(value)) for value in values):
            return None, MetricStatus.MISSING, "Missing or non-finite measured flow"
        try:
            total = fsum(float(value) for value in values)
        except OverflowError:
            return None, MetricStatus.MISSING, "Aggregate flow exceeds finite range"
        if not isfinite(total):
            return None, MetricStatus.MISSING, "Aggregate flow exceeds finite range"
        return total, MetricStatus.OK, None

    def fetch_history(self, start_date: date, end_date: date) -> list[MetricPoint]:
        if not self.csv_url:
            return [unavailable("etf_flow_usd", "Operator-configured ETF CSV", MetricStatus.PENDING)]
        try:
            response = self.client.get(self.csv_url)
            response.raise_for_status()
            frame = pd.read_csv(StringIO(response.text))
            if not {"date", "flow_usd"}.issubset(frame.columns):
                raise ValueError("ETF CSV requires date and flow_usd columns")
            frame["date"] = pd.to_datetime(frame["date"], utc=True, format="mixed").dt.normalize()
            if frame["date"].isna().any():
                raise ValueError("ETF CSV contains an undated observation")
            if "fund" not in frame:
                frame["fund"] = None
            frame["fund"] = frame["fund"].map(
                lambda value: str(value).strip().upper() if pd.notna(value) and str(value).strip() else None)
            expected_funds = set(frame["fund"].dropna()) - {"TOTAL"}
            frame = frame[(frame.date.dt.date >= start_date) & (frame.date.dt.date <= end_date)]
            fetched = datetime.now(timezone.utc)
            points = []
            for day, rows in frame.groupby("date", sort=True):
                value, status, error = self._daily_total(rows, expected_funds)
                points.append(MetricPoint(metric_name="etf_flow_usd", timestamp=day.to_pydatetime(),
                                          value=value, source="Configured ETF CSV", fetched_at=fetched,
                                          status=status, metadata={"fund": "TOTAL", "asset": "BTC",
                                                                   "effective_date": day.date().isoformat(), "error": error}))
            return points or [unavailable("etf_flow_usd", "Configured ETF CSV", MetricStatus.PENDING)]
        except Exception:
            return [unavailable("etf_flow_usd", "Configured ETF CSV")]

    def fetch_latest(self) -> list[MetricPoint]:
        today = datetime.now(timezone.utc).date()
        return self.fetch_history(today, today)
