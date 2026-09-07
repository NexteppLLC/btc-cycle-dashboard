"""Observable update quality, independent of optional paid-data availability."""
from datetime import datetime, timezone

from services.data_quality import current_metric_row, field, observation_date
from indicators.normalization import finite_number


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
    return {"as_of": as_of.isoformat(), "metric_points": metric_points, "etf_records": etf_records,
            "status": "error" if failures else "degraded" if warnings else "ok",
            "essential_failures": failures, "warnings": warnings, "sources": sources}
