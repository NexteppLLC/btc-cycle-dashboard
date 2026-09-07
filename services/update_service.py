"""Fault-isolated collection, calculation and persistence orchestration."""
from datetime import datetime, timedelta, timezone
import logging

import pandas as pd
import yaml

from collectors.btc_price import BTCPriceCollector
from collectors.etf_flow import ETFFlowCollector
from collectors.glassnode import GlassnodeCollector
from collectors.onchain import OnChainCollector
from collectors.cftc import CFTCCollector
from collectors.metals_price import MetalsPriceCollector
from collectors.metals_etf import MetalsETFCollector
from config.settings import ROOT, get_settings
from database.repository import Repository
from database.session import create_schema, session_scope
from indicators.etf import etf_aggregates
from indicators.holders import distribution_score, sth_state
from indicators.normalization import finite_number
from indicators.technical import calculate_technicals
from scoring.cycle_score import calculate_cycle_score
from scoring.regime import btc_minimum_data, classify_phase, weighted_confidence
from scoring.top_risk import calculate_top_risk
from scoring.metals import calculate_metals_scores, percentile, position_statistics
from services.data_quality import as_date, field, metric_current, metric_series, observation_date

logger = logging.getLogger(__name__)


def load_thresholds() -> dict:
    return yaml.safe_load((ROOT / "config" / "thresholds.yaml").read_text())


def _current_technicals(rows, metric_name, end):
    prices = metric_series(rows, metric_name, end)
    if metric_current(rows, metric_name, end) is None or prices.empty:
        return prices, {}
    if metric_name == "btc_price_usd":
        # BTC trades every day. Missing dates must not shorten calendar windows.
        prices.index = pd.DatetimeIndex(prices.index)
        prices = prices.asfreq("D")
    technicals = calculate_technicals(prices)
    return prices, {key: finite_number(value) for key, value in technicals.iloc[-1].items()}


def build_btc_inputs(rows, end):
    """Build only fresh, finite inputs; on-chain identities come from the collector."""
    names = {field(row, "metric_name") for row in rows}
    latest = {name: metric_current(rows, name, end) for name in names}
    _, current_tech = _current_technicals(rows, "btc_price_usd", end)
    flows = metric_series(rows, "etf_flow_usd", end)
    if not flows.empty:
        flows.index = pd.DatetimeIndex(flows.index)
        # A missing weekday is unknown, never a zero or an older substituted day.
        flows = flows.asfreq("B")
    flow = etf_aggregates(flows) if latest.get("etf_flow_usd") is not None else etf_aggregates(pd.Series(dtype=float))

    def rolling_z(name, window=365):
        if latest.get(name) is None:
            return None
        sample = metric_series(rows, name, end)
        sample = sample.loc[[day >= end - timedelta(days=window) for day in sample.index]].dropna()
        std = finite_number(sample.std())
        return float((sample.iloc[-1] - sample.mean()) / std) if len(sample) >= 30 and std is not None and std > 0 else None

    supply = metric_series(rows, "lth_supply", end)
    supply_change = None
    if latest.get("lth_supply") is not None and not supply.empty:
        previous = finite_number(supply.get(supply.index[-1] - timedelta(days=30)))
        if previous is not None and previous > 0:
            supply_change = (latest["lth_supply"] / previous - 1) * 100
    distribution_inputs = {"lth_sopr": latest.get("lth_sopr"),
                           "lth_spent_volume_z": rolling_z("lth_spent_volume"),
                           "lth_realized_profit_z": rolling_z("lth_realized_profit"),
                           "lth_supply_change_pct": supply_change, "cdd_z": rolling_z("cdd")}
    # Network-wide CDD alone cannot establish long-term-holder distribution.
    cohort_available = any(v is not None for k, v in distribution_inputs.items() if k != "cdd_z")
    distribution, coverage = distribution_score(distribution_inputs) if cohort_available else (None, 0.0)
    ma = current_tech.get("ma_200")
    deviation = current_tech["price"] / ma - 1 if ma is not None and ma > 0 else None
    values = {**latest, "global_mvrv": latest.get("global_mvrv"), "lth_distribution": distribution,
              "etf_flow": flow["7d"], "btc_trend": current_tech.get("return_30d"), "trend_deviation": deviation}
    state = sth_state(values)
    values["sth_state"] = 100 if state == "RECOVERY_CONFIRMATION" else 0 if state == "STH_STRESS" else None
    return values, flow, coverage


def btc_input_eligibility(values, flow, distribution_coverage, cfg):
    """Use the same current input completeness for persistence and display."""
    available = {"price": values.get("btc_price_usd") is not None,
                 "global_mvrv": values.get("global_mvrv") is not None,
                 "lth_mvrv": values.get("lth_mvrv") is not None,
                 "sth_mvrv": values.get("sth_mvrv") is not None,
                 "lth_distribution": distribution_coverage if values.get("lth_distribution") is not None else 0.0,
                 "mvrv_zscore": values.get("mvrv_zscore") is not None,
                 "etf": flow["7d"] is not None,
                 "sopr": any(values.get(k) is not None for k in ("lth_sopr", "sth_sopr", "asopr")),
                 "trend": values.get("btc_trend") is not None}
    confidence = weighted_confidence(available, cfg["confidence_weights"]["btc"])
    minimum_met, missing = btc_minimum_data(values)
    return {"minimum_met": minimum_met, "confidence": confidence,
            "missing": missing, "distribution_coverage": distribution_coverage,
            "distribution_value": values.get("lth_distribution"),
            "minimum_confidence": cfg.get("minimum_data", {}).get("phase_confidence", 50)}


def _sign_score(value, positive=75, negative=25, neutral=50):
    value = finite_number(value)
    return None if value is None else positive if value > 0 else negative if value < 0 else neutral


def etf_holdings_change(rows, end, max_age_days=5):
    """Mean sponsor holdings/share change; NAV and asset-value moves are excluded.

    Each comparison requires two dated, same-source snapshots within one week.
    This is a holdings signal, not an estimate of dollar capital flows.
    """
    funds = {}
    for row in rows:
        effective = as_date(field(row, "effective_date"))
        if str(field(row, "status")) != "OK" or effective is None or effective > end:
            continue
        key = (field(row, "fund"), field(row, "source"))
        funds.setdefault(key, {})[effective] = row
    changes = {}
    for (fund, source), dated in funds.items():
        days = sorted(dated)
        if len(days) < 2 or (end - days[-1]).days > max_age_days or (days[-1] - days[-2]).days > 7:
            continue
        current, previous = dated[days[-1]], dated[days[-2]]
        for name in ("ounces", "tonnes", "physical_holdings", "shares_outstanding"):
            if name == "physical_holdings" and (not field(current, "holdings_unit") or field(current, "holdings_unit") != field(previous, "holdings_unit")):
                continue
            a, b = finite_number(field(current, name)), finite_number(field(previous, name))
            if a is not None and a >= 0 and b is not None and b > 0:
                candidate = (days[-1], source, a / b - 1)
                if fund not in changes or candidate[:2] > changes[fund][:2]:
                    changes[fund] = candidate
                break
    return sum(item[2] for item in changes.values()) / len(changes) if changes else None


def build_metal_inputs(rows, cot_rows, fund_rows, asset, end):
    prices, technicals = _current_technicals(rows, f"{asset}_price_usd", end)
    cot = [row for row in cot_rows if field(row, "report_date") <= end]
    mm = [{key: field(row, key) if key == "report_date" or str(field(row, "status")) == "OK" else None
           for key in ("report_date", "long", "short", "net", "open_interest")}
          for row in cot if field(row, "category") == "managed_money"]
    mm.sort(key=lambda item: item["report_date"])
    cot_stale = bool(mm and (end - mm[-1]["report_date"]).days > 10)
    stats = position_statistics(mm) if not cot_stale else {}
    mm_52w = [row for row in mm if row["report_date"] > mm[-1]["report_date"] - timedelta(weeks=52)] if mm else []
    producer = {field(row, "report_date"): finite_number(field(row, "net"))
                for row in cot if field(row, "category") == "producer_merchant" and str(field(row, "status")) == "OK"}
    commercial_change = None
    if mm and not cot_stale:
        report_day = mm[-1]["report_date"]
        a, b = producer.get(report_day), producer.get(report_day - timedelta(weeks=1))
        if a is not None and b is not None:
            commercial_change = a - b
    etf_change = etf_holdings_change(fund_rows, end)
    # Match price movement to the COT reporting interval when weekly positions exist.
    price_change = None
    if technicals and mm and not cot_stale:
        report_day = mm[-1]["report_date"]
        dated_prices = {as_date(day): finite_number(value) for day, value in prices.items()}
        def price_on(day):
            eligible = [d for d in dated_prices if d <= day and (day - d).days <= 4 and dated_prices[d] is not None]
            return dated_prices[max(eligible)] if eligible else None
        a, b = price_on(report_day), price_on(report_day - timedelta(weeks=1))
        if a is not None and b is not None and b > 0:
            price_change = a / b - 1
    ma, price = technicals.get("ma_200"), technicals.get("price")
    above_ma = price > ma if price is not None and ma is not None and ma > 0 else None
    change_13w, mm_percentile = stats.get("change_13w"), stats.get("percentile_52w")
    oi_change = stats.get("oi_change_1w")
    oi_score = None
    if price_change is not None and oi_change is not None:
        oi_score = 75 if price_change > 0 and oi_change > 0 else 25 if price_change < 0 and oi_change > 0 else 50
    return {"price": price, "open_interest": stats.get("open_interest"), "mm_percentile": mm_percentile,
            "mm_long_percentile": percentile([x.get("long") for x in mm_52w], stats.get("long")),
            "mm_change": stats.get("change_1w"), "mm_trend_score": _sign_score(stats.get("change_4w")),
            "oi_change": oi_change, "oi_percentile": percentile([x.get("open_interest") for x in mm_52w], stats.get("open_interest")),
            "oi_score": oi_score, "commercial_change": commercial_change, "commercial_score": _sign_score(commercial_change),
            "etf_change": etf_change, "etf_score": _sign_score(etf_change), "price_change": price_change,
            "trend_score": 75 if above_ma is True else 25 if above_ma is False else None,
            "above_200dma": above_ma, "drawdown": technicals.get("drawdown_ath"),
            "position_reset": (70 if change_13w < 0 and mm_percentile > 20 else 40)
                              if change_13w is not None and mm_percentile is not None else None,
            "oi_reset": (70 if oi_change < 0 else 40) if oi_change is not None else None,
            "reaccumulation": _sign_score(stats.get("change_1w"), positive=70, negative=40, neutral=50),
            "estimated_flow": False, "cot_stale": cot_stale}


def run_update(days: int = 1500) -> dict:
    settings = get_settings()
    create_schema()
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=days)
    collectors = [BTCPriceCollector(timeout=settings.http_timeout_seconds), OnChainCollector(timeout=settings.http_timeout_seconds),
                  GlassnodeCollector(settings.glassnode_api_key, timeout=settings.http_timeout_seconds),
                  ETFFlowCollector(settings.etf_flow_csv_url, timeout=settings.http_timeout_seconds)]
    collectors += [MetalsPriceCollector(asset, timeout=settings.http_timeout_seconds) for asset in ("gold", "silver")]
    points = []
    for collector in collectors:
        try:
            points.extend(collector.fetch_history(start, end))
        except Exception as exc:
            logger.error("Collector boundary failure: %s", type(exc).__name__)
    with session_scope() as session:
        repo = Repository(session)
        repo.upsert_metrics(points)
        session.flush()
        try:
            etf_collector = MetalsETFCollector(timeout=settings.http_timeout_seconds)
            etf_records = etf_collector.fetch_history(start, end)
            etf_saved = repo.upsert_etf_holdings(etf_records)
            session.flush()
            logger.info("ETF normalized objects=%d repository upserts=%d", len(etf_records), etf_saved)
        except Exception as exc:
            etf_saved = 0
            logger.error("Metals ETF collection failed: %s", type(exc).__name__)
        rows = repo.metrics()
        values, flow, dist_coverage = build_btc_inputs(rows, end)
        cfg = load_thresholds()
        cycle = calculate_cycle_score(values, cfg["cycle"])
        top = calculate_top_risk(values, cfg["top_risk"])
        eligibility = btc_input_eligibility(values, flow, dist_coverage, cfg)
        confidence, minimum_met = eligibility["confidence"], eligibility["minimum_met"]
        phase = classify_phase(cycle.score, top.score, values.get("btc_trend"), values.get("lth_distribution"),
                               values.get("sth_mvrv"), cfg, minimum_met=minimum_met, confidence=confidence)
        snapshot_values = {name: values.get(name) for name in ("global_mvrv", "mvrv_zscore", "lth_mvrv", "sth_mvrv",
                           "lth_realized_price", "sth_realized_price", "lth_sopr", "sth_sopr", "lth_spent_volume", "sth_spent_volume", "lth_distribution")}
        snapshot = repo.upsert_snapshot({**snapshot_values, "date": end, "btc_price": values.get("btc_price_usd"),
                                        "etf_flow_1d": flow["today"], "etf_flow_7d": flow["7d"], "cycle_score": cycle.score,
                                        "top_risk_score": top.score, "cycle_phase": phase, "confidence": confidence})
        repo.replace_scoring_details(end, cycle.details + top.details)
        metal_snapshots = []
        for asset in ("gold", "silver"):
            try:
                cot_records = CFTCCollector(asset, timeout=settings.http_timeout_seconds).fetch_history(end - timedelta(days=max(days, 3650)), end)
                repo.upsert_cot(cot_records)
                session.flush()
            except Exception as exc:
                logger.error("%s CFTC collection failed: %s", asset, type(exc).__name__)
            metal_values = build_metal_inputs(rows, repo.cot(asset), repo.etf_holdings(asset), asset, end)
            scores = calculate_metals_scores(metal_values, cfg["metals"], asset)
            metal_snapshots.append(repo.upsert_metal_snapshot({"asset": asset.upper(), "date": end, "price": metal_values["price"],
                                   "demand_score": scores.demand, "top_risk_score": scores.top_risk, "dip_quality_score": scores.dip_quality,
                                   "phase": scores.phase, "confidence": scores.confidence, "divergence": scores.divergence}))
        return {"snapshot": snapshot, "metals": metal_snapshots, "points": len(points),
                "etf_records": etf_saved, "distribution_coverage": dist_coverage}
