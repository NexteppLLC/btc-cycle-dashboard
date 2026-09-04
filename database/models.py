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
    asset: Mapped[str | None] = mapped_column(String(12), nullable=True)
    price_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)


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


class COTPosition(Base):
    """Weekly CFTC disaggregated position (never forward-filled to daily rows)."""
    __tablename__ = "cot_positions"
    __table_args__ = (UniqueConstraint("asset", "report_date", "category", name="uq_cot_asset_week_category"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset: Mapped[str] = mapped_column(String(12), index=True)
    report_date: Mapped[date] = mapped_column(Date, index=True)
    category: Mapped[str] = mapped_column(String(40))
    long: Mapped[float | None] = mapped_column(Float)
    short: Mapped[float | None] = mapped_column(Float)
    spreading: Mapped[float | None] = mapped_column(Float)
    net: Mapped[float | None] = mapped_column(Float)
    open_interest: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(200))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(40))


class ETFHolding(Base):
    __tablename__ = "etf_holdings"
    __table_args__ = (UniqueConstraint("asset", "fund", "date", name="uq_etf_asset_fund_day"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset: Mapped[str] = mapped_column(String(12), index=True)
    fund: Mapped[str] = mapped_column(String(20), index=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    shares_outstanding: Mapped[float | None] = mapped_column(Float)
    ounces: Mapped[float | None] = mapped_column(Float)
    tonnes: Mapped[float | None] = mapped_column(Float)
    nav: Mapped[float | None] = mapped_column(Float)
    physical_holdings: Mapped[float | None] = mapped_column(Float, nullable=True)
    holdings_unit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    net_assets: Mapped[float | None] = mapped_column(Float, nullable=True)
    flow: Mapped[float | None] = mapped_column(Float)
    flow_status: Mapped[str] = mapped_column(String(40), default="UNAVAILABLE")
    source: Mapped[str] = mapped_column(String(200))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(40), default="OK")
    effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)


class MetalsSnapshot(Base):
    __tablename__ = "metals_snapshot"
    __table_args__ = (UniqueConstraint("asset", "date", name="uq_metals_asset_day"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset: Mapped[str] = mapped_column(String(12), index=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    price: Mapped[float | None] = mapped_column(Float)
    demand_score: Mapped[float | None] = mapped_column(Float)
    top_risk_score: Mapped[float | None] = mapped_column(Float)
    dip_quality_score: Mapped[float | None] = mapped_column(Float)
    phase: Mapped[str] = mapped_column(String(30), default="UNKNOWN")
    confidence: Mapped[float] = mapped_column(Float, default=0)
    divergence: Mapped[str] = mapped_column(String(40), default="NONE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
