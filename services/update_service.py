"""Fault-isolated collection, calculation and persistence orchestration."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import logging

import pandas as pd
import yaml

from collectors.btc_price import BTCPriceCollector
from collectors.coinmetrics import CoinMetricsCollector
from collectors.etf_flow import ETFFlowCollector
from collectors.glassnode import GlassnodeCollector
from config.settings import ROOT, get_settings
from database.repository import Repository
from database.session import create_schema, session_scope
from indicators.etf import etf_aggregates
from indicators.holders import distribution_score
from indicators.mvrv import calculate_mvrv
from indicators.technical import calculate_technicals
from scoring.cycle_score import calculate_cycle_score
from scoring.regime import calculate_confidence, classify_phase
from scoring.top_risk import calculate_top_risk

logger = logging.getLogger(__name__)


def load_thresholds() -> dict:
    return yaml.safe_load((ROOT / "config" / "thresholds.yaml").read_text())


def run_update(days: int = 1500) -> dict:
    settings = get_settings(); create_schema(); end = datetime.now(timezone.utc).date(); start = end - timedelta(days=days)
    collectors = [CoinMetricsCollector(timeout=settings.http_timeout_seconds), BTCPriceCollector(timeout=settings.http_timeout_seconds), GlassnodeCollector(settings.glassnode_api_key, timeout=settings.http_timeout_seconds), ETFFlowCollector(settings.etf_flow_csv_url, timeout=settings.http_timeout_seconds)]
    points = []
    for collector in collectors:
        try: points.extend(collector.fetch_history(start, end))
        except Exception as exc: logger.error("Collector boundary failure: %s", type(exc).__name__)
    with session_scope() as session:
        repo = Repository(session); repo.upsert_metrics(points); session.flush()
        rows = repo.metrics()
        by_name: dict[str, list] = {}
        for row in rows: by_name.setdefault(row.metric_name, []).append(row)
        latest = {name: next((r.value for r in reversed(items) if r.value is not None), None) for name, items in by_name.items()}
        price_rows = by_name.get("btc_price_usd", []); prices = pd.Series({r.date: r.value for r in price_rows if r.value is not None}, dtype=float)
        tech = calculate_technicals(prices) if not prices.empty else pd.DataFrame()
        current_tech = tech.iloc[-1].to_dict() if not tech.empty else {}
        flow_rows = by_name.get("etf_flow_usd", []); flow = etf_aggregates(pd.Series([r.value for r in flow_rows]))
        distribution, dist_coverage = distribution_score({"lth_sopr": latest.get("lth_sopr")})
        values = {**latest, "global_mvrv": latest.get("global_mvrv") or calculate_mvrv(latest.get("market_cap_usd"), latest.get("realized_cap_usd")), "lth_distribution": distribution, "etf_flow": flow["7d"], "btc_trend": current_tech.get("return_30d"), "trend_deviation": (current_tech.get("price") / current_tech.get("ma_200") - 1) if current_tech.get("ma_200") else None}
        cfg = load_thresholds(); cycle = calculate_cycle_score(values, cfg["cycle"]); top = calculate_top_risk(values, cfg["top_risk"])
        phase = classify_phase(cycle.score, top.score, values.get("btc_trend"), distribution, values.get("sth_mvrv"), cfg)
        glassnode_ok = any(p.source.startswith("Glassnode") and p.value is not None for p in points)
        confidence = calculate_confidence(coverage=min(cycle.coverage, top.coverage) if top.coverage else cycle.coverage, glassnode=glassnode_ok, etf_current=flow["today"] is not None, history_sufficient=len(prices) >= 200, config=cfg)
        snapshot = repo.upsert_snapshot({"date": end, "btc_price": latest.get("btc_price_usd"), "global_mvrv": values["global_mvrv"], "mvrv_zscore": latest.get("mvrv_zscore"), "lth_mvrv": latest.get("lth_mvrv"), "sth_mvrv": latest.get("sth_mvrv"), "lth_realized_price": latest.get("lth_realized_price"), "sth_realized_price": latest.get("sth_realized_price"), "lth_sopr": latest.get("lth_sopr"), "sth_sopr": latest.get("sth_sopr"), "lth_spent_volume": latest.get("lth_spent_volume"), "sth_spent_volume": latest.get("sth_spent_volume"), "etf_flow_1d": flow["today"], "etf_flow_7d": flow["7d"], "lth_distribution": distribution, "cycle_score": cycle.score, "top_risk_score": top.score, "cycle_phase": phase, "confidence": confidence})
        repo.replace_scoring_details(end, cycle.details + top.details)
        return {"snapshot": snapshot, "points": len(points), "distribution_coverage": dist_coverage}

