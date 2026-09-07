"""Observable update quality, independent of optional paid-data availability."""
from datetime import datetime, timezone

from services.data_quality import MAX_AGE_DAYS, current_metric_row, field, latest_metric_record, observation_date
from indicators.normalization import finite_number


BTC_OPTIONAL_METRICS = ("lth_mvrv", "sth_mvrv", "mvrv_zscore", "lth_realized_price",
                        "sth_realized_price", "lth_sopr", "sth_sopr", "lth_supply",
                        "sth_supply", "lth_spent_volume", "lth_realized_profit", "cdd", "etf_flow_usd")


def metric_diagnostic(metrics, name, as_of):
    """Expose the current value's date or the latest explicit failure reason."""
    row = current_metric_row(metrics, name, as_of)
    if row is not None:
        return {"status": "OK", "source": field(row, "source"),
                "effective_date": str(observation_date(row)), "reason": None}
    latest = latest_metric_record(metrics, name, as_of)
    status = str(field(latest, "status", "MISSING"))
    day = observation_date(latest)
    if status == "OK":
        status = "STALE" if day and (as_of - day).days > MAX_AGE_DAYS.get(name, 3) else "MISSING"
    reasons = {"MISSING": "観測値がありません", "STALE": "観測値が期限切れです",
               "UNAVAILABLE_NO_API_KEY": "Glassnode APIキーが未設定です",
               "UNAVAILABLE_PLAN": "API認証または指標の利用権限を確認してください",
               "UNAVAILABLE": "取得元でこの指標を利用できません",
               "ERROR": "取得元への接続またはデータ解析に失敗しました",
               "PENDING": "公開待ち、または取得元が未設定です"}
    return {"status": status, "source": field(latest, "source"),
            "effective_date": str(day) if day and finite_number(field(latest, "value")) is not None else None,
            "last_record_date": str(day) if day else None,
            "reason": reasons.get(status, "観測値を確認できません")}


def build_diagnostics(metrics, cot, etfs, *, as_of=None, metric_points=0, etf_records=0):
    as_of = as_of or datetime.now(timezone.utc).date()
    sources, warnings, failures = {}, [], []
    for asset in ("btc", "gold", "silver"):
        name = f"{asset}_price_usd"
        row = current_metric_row(metrics, name, as_of)
        sources[name] = {
            "status": "OK" if row is not None else "UNAVAILABLE_OR_STALE",
            "source": field(row, "source"),
            "effective_date": str(observation_date(row)) if row is not None else None,
            "price_type": field(row, "price_type"),
        }
        if row is None:
            failures.append(f"{asset.upper()}: fresh measured price unavailable")
    mvrv = current_metric_row(metrics, "global_mvrv", as_of)
    sources["global_mvrv"] = {"status": "OK" if mvrv is not None else "UNAVAILABLE_OR_STALE"}
    if mvrv is None:
        warnings.append("BTC: free Global MVRV unavailable or stale")
    for name in BTC_OPTIONAL_METRICS:
        sources[name] = metric_diagnostic(metrics, name, as_of)
    missing_cohorts = [name for name in ("lth_mvrv", "sth_mvrv") if sources[name]["status"] != "OK"]
    if missing_cohorts:
        warnings.append("BTC: cohort MVRV unavailable: " + ", ".join(missing_cohorts))
    if sources["etf_flow_usd"]["status"] != "OK":
        warnings.append("BTC: measured ETF dollar flows unavailable or stale")
    for asset in ("GOLD", "SILVER"):
        candidates = [r for r in cot if field(r, "asset") == asset
                      and field(r, "category") == "managed_money"
                      and field(r, "report_date") is not None and field(r, "report_date") <= as_of]
        latest = max(candidates, key=lambda r: field(r, "report_date")) if candidates else None
        current = latest is not None and field(latest, "status") == "OK" and (as_of - field(latest, "report_date")).days <= 10
        current = current and all(finite_number(field(latest, key)) is not None for key in ("long", "short", "open_interest"))
        sources[f"{asset.lower()}_cot"] = {"status": "OK" if current else "UNAVAILABLE_OR_STALE"}
        if not current:
            warnings.append(f"{asset}: weekly CFTC positions unavailable or stale")
    for fund in ("GLD", "IAU", "SLV"):
        current = [r for r in etfs if field(r, "fund") == fund and field(r, "status") == "OK"
                   and field(r, "effective_date") is not None
                   and 0 <= (as_of - field(r, "effective_date")).days <= 5]
        row = max(current, key=lambda r: field(r, "effective_date")) if current else None
        fields = [key for key in ("physical_holdings", "ounces", "tonnes", "shares_outstanding", "net_assets")
                  if finite_number(field(row, key)) is not None]
        has_holdings = any(key in fields for key in ("physical_holdings", "ounces", "tonnes", "shares_outstanding"))
        sources[fund] = {"status": "OK" if has_holdings else "PARTIAL_FIELDS" if row is not None else "UNAVAILABLE_OR_STALE",
                         "effective_date": str(field(row, "effective_date")) if row is not None else None,
                         "fields": fields}
        if row is None:
            warnings.append(f"{fund}: dated official ETF holdings unavailable or stale")
        elif not has_holdings:
            warnings.append(f"{fund}: net assets available, but physical holdings/shares are missing")
    # Recheck decision inputs at display time: a recent saved score can depend
    # on observations that have since expired or failed to update.
    from services.update_service import build_btc_inputs, btc_input_eligibility, load_thresholds
    values, flow, coverage = build_btc_inputs(metrics, as_of)
    eligibility = {"btc": btc_input_eligibility(values, flow, coverage, load_thresholds())}
    for asset in ("gold", "silver"):
        eligible = all(sources[f"{asset}_{suffix}"]["status"] == "OK" for suffix in ("price_usd", "cot"))
        eligibility[asset] = {"minimum_met": eligible}
    return {"as_of": as_of.isoformat(), "metric_points": metric_points, "etf_records": etf_records,
            "status": "error" if failures else "degraded" if warnings else "ok",
            "essential_failures": failures, "warnings": warnings, "sources": sources,
            "phase_eligibility": eligibility}
