"""Fault-isolated collection, calculation and persistence orchestration."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import logging

import pandas as pd
import yaml

from collectors.btc_price import BTCPriceCollector
from collectors.etf_flow import ETFFlowCollector
from collectors.glassnode import GlassnodeCollector
from collectors.cftc import CFTCCollector
from collectors.metals_price import MetalsPriceCollector
from collectors.metals_etf import MetalsETFCollector
from config.settings import ROOT, get_settings
from database.repository import Repository
from database.session import create_schema, session_scope
from indicators.etf import etf_aggregates
from indicators.holders import distribution_score
from indicators.mvrv import calculate_mvrv
from indicators.technical import calculate_technicals
from scoring.cycle_score import calculate_cycle_score
from scoring.regime import btc_minimum_data, classify_phase, weighted_confidence
from scoring.top_risk import calculate_top_risk
from scoring.metals import calculate_metals_scores, percentile, position_statistics

logger = logging.getLogger(__name__)


def load_thresholds() -> dict:
    return yaml.safe_load((ROOT / "config" / "thresholds.yaml").read_text())


def run_update(days: int = 1500) -> dict:
    settings = get_settings(); create_schema(); end = datetime.now(timezone.utc).date(); start = end - timedelta(days=days)
    collectors = [BTCPriceCollector(timeout=settings.http_timeout_seconds), GlassnodeCollector(settings.glassnode_api_key, timeout=settings.http_timeout_seconds), ETFFlowCollector(settings.etf_flow_csv_url, timeout=settings.http_timeout_seconds)]
    collectors += [MetalsPriceCollector(asset, timeout=settings.http_timeout_seconds) for asset in ("gold", "silver")]
    points = []
    for collector in collectors:
        try: points.extend(collector.fetch_history(start, end))
        except Exception as exc: logger.error("Collector boundary failure: %s", type(exc).__name__)
    with session_scope() as session:
        repo = Repository(session); repo.upsert_metrics(points); session.flush()
        try:
            etf_records = MetalsETFCollector(timeout=settings.http_timeout_seconds).fetch_history(start, end)
            repo.upsert_etf_holdings(etf_records); session.flush()
        except Exception as exc:
            etf_records = []; logger.error("Metals ETF collection failed: %s", type(exc).__name__)
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
        btc_available = {"price": values.get("btc_price_usd") is not None, "lth_mvrv": values.get("lth_mvrv") is not None,
            "sth_mvrv": values.get("sth_mvrv") is not None, "lth_distribution": distribution is not None,
            "mvrv_zscore": values.get("mvrv_zscore") is not None, "etf": flow["today"] is not None,
            "trend": values.get("btc_trend") is not None}
        confidence = weighted_confidence(btc_available, cfg["confidence_weights"]["btc"])
        minimum_met, _ = btc_minimum_data(values)
        phase = classify_phase(cycle.score, top.score, values.get("btc_trend"), distribution, values.get("sth_mvrv"), cfg,
            minimum_met=minimum_met, confidence=confidence)
        snapshot = repo.upsert_snapshot({"date": end, "btc_price": latest.get("btc_price_usd"), "global_mvrv": values["global_mvrv"], "mvrv_zscore": latest.get("mvrv_zscore"), "lth_mvrv": latest.get("lth_mvrv"), "sth_mvrv": latest.get("sth_mvrv"), "lth_realized_price": latest.get("lth_realized_price"), "sth_realized_price": latest.get("sth_realized_price"), "lth_sopr": latest.get("lth_sopr"), "sth_sopr": latest.get("sth_sopr"), "lth_spent_volume": latest.get("lth_spent_volume"), "sth_spent_volume": latest.get("sth_spent_volume"), "etf_flow_1d": flow["today"], "etf_flow_7d": flow["7d"], "lth_distribution": distribution, "cycle_score": cycle.score, "top_risk_score": top.score, "cycle_phase": phase, "confidence": confidence})
        repo.replace_scoring_details(end, cycle.details + top.details)
        metal_snapshots = []
        for asset in ("gold", "silver"):
            try:
                cot_records = CFTCCollector(asset, timeout=settings.http_timeout_seconds).fetch_history(end - timedelta(days=max(days, 3650)), end)
                repo.upsert_cot(cot_records); session.flush()
            except Exception as exc:
                logger.error("%s CFTC collection failed: %s", asset, type(exc).__name__)
            cot_rows = repo.cot(asset)
            mm = [{"report_date": r.report_date, "long": r.long, "short": r.short, "net": r.net, "open_interest": r.open_interest} for r in cot_rows if r.category == "managed_money"]
            producer = [r for r in cot_rows if r.category == "producer_merchant"]
            stats = position_statistics(mm)
            fund_rows = [r for r in repo.etf_holdings(asset) if any(v is not None for v in (r.ounces, r.tonnes, r.nav, r.shares_outstanding))]
            fund_changes = []
            for fund in {r.fund for r in fund_rows}:
                fr = [r for r in fund_rows if r.fund == fund]
                if len(fr) > 1:
                    current, prior = fr[-1], fr[-2]
                    for field in ("ounces", "tonnes", "nav", "shares_outstanding"):
                        a, b = getattr(current, field), getattr(prior, field)
                        if a is not None and b not in (None, 0): fund_changes.append(a / b - 1); break
            etf_change = sum(fund_changes) / len(fund_changes) if fund_changes else None
            metal_prices = pd.Series({r.date: r.value for r in by_name.get(f"{asset}_price_usd", []) if r.value is not None}, dtype=float)
            mtech = calculate_technicals(metal_prices) if not metal_prices.empty else pd.DataFrame(); mt = mtech.iloc[-1].to_dict() if not mtech.empty else {}
            pchange = float(metal_prices.pct_change().iloc[-1]) if len(metal_prices)>1 else None
            values_m = {"price": mt.get("price"), "open_interest": stats.get("open_interest"), "mm_percentile": stats.get("percentile_52w"), "mm_long_percentile": percentile([x["long"] for x in mm[-52:] if x.get("long") is not None], stats.get("long"), 20) if stats.get("long") is not None else None,
                "mm_change": stats.get("change_1w"), "mm_trend_score": 75 if (stats.get("change_4w") or 0)>0 else 25,
                "oi_change": stats.get("oi_change_1w"), "oi_percentile": percentile([x["open_interest"] for x in mm[-52:] if x.get("open_interest") is not None], stats.get("open_interest"), 20) if stats.get("open_interest") is not None else None,
                "oi_score": 75 if pchange is not None and pchange>0 and (stats.get("oi_change_1w") or 0)>0 else 50,
                "commercial_change": producer[-1].net-producer[-2].net if len(producer)>1 and producer[-1].net is not None and producer[-2].net is not None else None,
                "commercial_score": 75 if len(producer)>1 and producer[-1].net is not None and producer[-2].net is not None and producer[-1].net>producer[-2].net else 50,
                "etf_change": etf_change, "etf_score": 75 if etf_change is not None and etf_change > 0 else 25 if etf_change is not None else None,
                "price_change": pchange, "trend_score": 75 if mt.get("ma_200") and mt.get("price",0)>mt["ma_200"] else (25 if mt.get("ma_200") else None),
                "above_200dma": (mt.get("price",0)>mt["ma_200"]) if mt.get("ma_200") else None, "drawdown": mt.get("drawdown_ath"),
                "position_reset": 70 if stats.get("change_13w") is not None and stats["change_13w"]<0 and (stats.get("percentile_52w") or 0)>20 else 40,
                "oi_reset": 70 if (stats.get("oi_change_1w") or 0)<0 else 40, "reaccumulation": 70 if (stats.get("change_1w") or 0)>0 else 40,
                "cot_stale": bool(mm and (end-mm[-1]["report_date"]).days>10)}
            scores = calculate_metals_scores(values_m, cfg["metals"], asset)
            metal_snapshots.append(repo.upsert_metal_snapshot({"asset": asset.upper(), "date": end, "price": mt.get("price"), "demand_score": scores.demand,
                "top_risk_score": scores.top_risk, "dip_quality_score": scores.dip_quality, "phase": scores.phase, "confidence": scores.confidence, "divergence": scores.divergence}))
        return {"snapshot": snapshot, "metals": metal_snapshots, "points": len(points),
                "etf_records": len(etf_records), "distribution_coverage": dist_coverage}
