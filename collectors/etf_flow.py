"""ETF flow ingestion from an operator-approved structured CSV feed.

No brittle HTML scraping is performed. Without a configured URL the state is
PENDING rather than zero or a copied prior value.
"""
from datetime import date, datetime, timezone
from io import StringIO

import pandas as pd

from .base import HTTPCollector, MetricPoint, MetricStatus, unavailable


class ETFFlowCollector(HTTPCollector):
    def __init__(self, csv_url: str | None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.csv_url = csv_url

    def fetch_history(self, start_date: date, end_date: date) -> list[MetricPoint]:
        if not self.csv_url:
            return [unavailable("etf_flow_usd", "Operator-configured ETF CSV", MetricStatus.PENDING)]
        try:
            response = self.client.get(self.csv_url)
            response.raise_for_status()
            frame = pd.read_csv(StringIO(response.text))
            if not {"date", "flow_usd"}.issubset(frame.columns):
                raise ValueError("ETF CSV requires date and flow_usd columns")
            frame["date"] = pd.to_datetime(frame["date"], utc=True)
            frame = frame[(frame.date.dt.date >= start_date) & (frame.date.dt.date <= end_date)]
            fetched = datetime.now(timezone.utc)
            points = []
            for row in frame.itertuples():
                points.append(MetricPoint(metric_name="etf_flow_usd", timestamp=row.date.to_pydatetime(), value=None if pd.isna(row.flow_usd) else float(row.flow_usd), source="Configured ETF CSV", fetched_at=fetched, status=MetricStatus.MISSING if pd.isna(row.flow_usd) else MetricStatus.OK, metadata={"fund": getattr(row, "fund", "TOTAL")}))
            return points or [unavailable("etf_flow_usd", "Configured ETF CSV", MetricStatus.PENDING)]
        except Exception:
            return [unavailable("etf_flow_usd", "Configured ETF CSV")]

    def fetch_latest(self) -> list[MetricPoint]:
        today = datetime.now(timezone.utc).date()
        return self.fetch_history(today, today)
