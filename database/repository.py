"""Idempotent metric and snapshot repository."""
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from collectors.base import MetricPoint
from .models import DailySnapshot, Metric, ScoringDetail


class Repository:
    def __init__(self, session: Session): self.session = session

    def upsert_metrics(self, points: list[MetricPoint]) -> None:
        for point in points:
            key = {"date": point.timestamp.date(), "metric_name": point.metric_name, "source": point.source}
            row = self.session.scalar(select(Metric).filter_by(**key))
            values = {**key, "timestamp": point.timestamp, "value": point.value, "status": point.status.value, "fetched_at": point.fetched_at}
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

