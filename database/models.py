"""SQLAlchemy models with daily idempotency constraints."""
from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase): pass


class Metric(Base):
    __tablename__ = "metrics"
    __table_args__ = (UniqueConstraint("date", "metric_name", "source", name="uq_metric_daily_source"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    metric_name: Mapped[str] = mapped_column(String(80), index=True)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(40))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DailySnapshot(Base):
    __tablename__ = "daily_snapshot"
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    btc_price: Mapped[float | None] = mapped_column(Float)
    global_mvrv: Mapped[float | None] = mapped_column(Float)
    mvrv_zscore: Mapped[float | None] = mapped_column(Float)
    lth_mvrv: Mapped[float | None] = mapped_column(Float)
    sth_mvrv: Mapped[float | None] = mapped_column(Float)
    lth_realized_price: Mapped[float | None] = mapped_column(Float)
    sth_realized_price: Mapped[float | None] = mapped_column(Float)
    lth_sopr: Mapped[float | None] = mapped_column(Float)
    sth_sopr: Mapped[float | None] = mapped_column(Float)
    lth_spent_volume: Mapped[float | None] = mapped_column(Float)
    sth_spent_volume: Mapped[float | None] = mapped_column(Float)
    etf_flow_1d: Mapped[float | None] = mapped_column(Float)
    etf_flow_7d: Mapped[float | None] = mapped_column(Float)
    lth_distribution: Mapped[float | None] = mapped_column(Float)
    cycle_score: Mapped[float | None] = mapped_column(Float)
    top_risk_score: Mapped[float | None] = mapped_column(Float)
    cycle_phase: Mapped[str] = mapped_column(String(30), default="UNKNOWN")
    confidence: Mapped[float] = mapped_column(Float, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class ScoringDetail(Base):
    __tablename__ = "scoring_detail"
    __table_args__ = (UniqueConstraint("date", "component", name="uq_score_component_daily"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    component: Mapped[str] = mapped_column(String(80))
    raw_value: Mapped[float | None] = mapped_column(Float)
    normalized_score: Mapped[float | None] = mapped_column(Float)
    weight: Mapped[float] = mapped_column(Float)
    contribution: Mapped[float | None] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(String(500))

