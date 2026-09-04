"""Idempotent metric and snapshot repository."""
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from collectors.base import MetricPoint
from .models import COTPosition, DailySnapshot, ETFHolding, MetalsSnapshot, Metric, ScoringDetail


class Repository:
    def __init__(self, session: Session): self.session = session

    def upsert_metrics(self, points: list[MetricPoint]) -> None:
        for point in points:
            key = {"date": point.timestamp.date(), "metric_name": point.metric_name, "source": point.source}
            row = self.session.scalar(select(Metric).filter_by(**key))
            effective_date = point.metadata.get("effective_date")
            if isinstance(effective_date, str): effective_date = date.fromisoformat(effective_date)
            values = {**key, "timestamp": point.timestamp, "value": point.value, "status": point.status.value, "fetched_at": point.fetched_at,
                      "asset": point.metadata.get("asset"), "price_type": point.metadata.get("price_type"),
                      "effective_date": effective_date, "error": point.metadata.get("error")}
            if row:
                for name, value in values.items(): setattr(row, name, value)
            else: self.session.add(Metric(**values))

    def upsert_snapshot(self, values: dict) -> DailySnapshot:
        row = self.session.get(DailySnapshot, values["date"])
        if row:
            for name, value in values.items(): setattr(row, name, value)
        else:
            row = DailySnapshot(**values); self.session.add(row)
        return row

    def replace_scoring_details(self, day: date, details: list[dict]) -> None:
        existing = {x.component: x for x in self.session.scalars(select(ScoringDetail).where(ScoringDetail.date == day))}
        for item in details:
            row = existing.get(item["component"])
            if row:
                for name, value in item.items(): setattr(row, name, value)
            else: self.session.add(ScoringDetail(date=day, **item))

    def metrics(self, metric_name: str | None = None) -> list[Metric]:
        query = select(Metric).order_by(Metric.timestamp)
        if metric_name: query = query.where(Metric.metric_name == metric_name)
        return list(self.session.scalars(query))

    def snapshots(self, limit: int = 1500) -> list[DailySnapshot]:
        return list(self.session.scalars(select(DailySnapshot).order_by(DailySnapshot.date.desc()).limit(limit)))[::-1]

    def upsert_cot(self, records: list[dict]) -> None:
        for values in records:
            key = {k: values[k] for k in ("asset", "report_date", "category")}
            row = self.session.scalar(select(COTPosition).filter_by(**key))
            if row:
                for name, value in values.items(): setattr(row, name, value)
            else: self.session.add(COTPosition(**values))

    def cot(self, asset: str, limit: int = 2000) -> list[COTPosition]:
        query = select(COTPosition).where(COTPosition.asset == asset.upper()).order_by(COTPosition.report_date.desc()).limit(limit)
        return list(self.session.scalars(query))[::-1]

    def upsert_metal_snapshot(self, values: dict) -> MetalsSnapshot:
        row = self.session.scalar(select(MetalsSnapshot).filter_by(asset=values["asset"], date=values["date"]))
        if row:
            for name, value in values.items(): setattr(row, name, value)
        else: row = MetalsSnapshot(**values); self.session.add(row)
        return row

    def upsert_etf_holdings(self, records: list[dict]) -> int:
        saved = 0
        for values in records:
            # HTTP/schema diagnostics are not holdings. Persist only an OK
            # snapshot with at least one sponsor-measured summary value.
            if values.get("status") != "OK" or not any(
                    values.get(field) is not None
                    for field in ("physical_holdings", "shares_outstanding", "net_assets")):
                continue
            key = {k: values[k] for k in ("asset", "fund", "date")}
            row = self.session.scalar(select(ETFHolding).filter_by(**key))
            if row:
                for name, value in values.items(): setattr(row, name, value)
            else: self.session.add(ETFHolding(**values))
            saved += 1
        return saved

    def etf_holdings(self, asset: str | None = None) -> list[ETFHolding]:
        query = select(ETFHolding).order_by(ETFHolding.date)
        if asset: query = query.where(ETFHolding.asset == asset.upper())
        return list(self.session.scalars(query))

    def metal_snapshots(self, asset: str | None = None) -> list[MetalsSnapshot]:
        query = select(MetalsSnapshot).order_by(MetalsSnapshot.date)
        if asset: query = query.where(MetalsSnapshot.asset == asset.upper())
        return list(self.session.scalars(query))
