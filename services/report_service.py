"""Japanese daily report; partial/stale inputs never imply a safe market."""
from math import isfinite
from pathlib import Path
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from config.settings import ROOT
from services.phase_service import phase_status


def fmt(value, suffix="", digits=2):
    return "取得不可" if value is None or not isfinite(float(value)) else f"{value:,.{digits}f}{suffix}"


def _quote_fields(q):
    if q is None: return None
    get = (lambda k, d=None: q.get(k, d)) if isinstance(q, dict) else (lambda k, d=None: getattr(q, k, d))
    meta = get("metadata", {}) or {}
    if not meta:  # ORM/Streamlit serialization stores provenance as columns.
        meta = {k:get(k) for k in ("asset","symbol","price_type","unit","market_state","freshness","age_minutes","change_24h_pct","previous_report_pct")}
        meta["24h_change_pct"] = meta.pop("change_24h_pct", None)
    return {"asset":meta.get("asset"), "value":get("value"), "observed":get("timestamp"), "fetched":get("fetched_at"),
            "source":get("source"), "status":str(get("status")), **meta}


def report_text(snapshot, *, metals=(), diagnostics=None, core5=None, quotes=()) -> str:
    as_of = date.fromisoformat(diagnostics["as_of"]) if diagnostics else datetime.now(timezone.utc).date()
    status = phase_status(snapshot.cycle_phase, snapshot.confidence, snapshot.date,
                          diagnostics=diagnostics, as_of=as_of)
    stale, partial = status.stale, status.partial
    reference = "（参考値）" if partial else ""
    phase = status.label
    quote_map = {x["asset"]:x for x in map(_quote_fields, quotes) if x and x.get("asset")}
    generated = datetime.now(timezone.utc).astimezone(ZoneInfo("Asia/Tokyo"))
    text = f"""# BTC / Gold / Silver 日次レポート

保存済み集計日（UTC）：{snapshot.date.isoformat()}
判定確認日（UTC）：{as_of.isoformat()}
レポート生成（JST）：{generated:%Y-%m-%d %H:%M}

| 資産 | 最新価格 | 観測時刻 | 24h | 前回レポート比 | 相場局面 | Confidence |
|---|---:|---|---:|---:|---|---:|
"""
    metal_map = {m.asset.upper():m for m in metals}
    for asset in ("BTC", "GOLD", "SILVER"):
        q=quote_map.get(asset); m=metal_map.get(asset)
        unit = "USD" if asset == "BTC" else "USD / troy oz (FUTURES_PROXY)"
        price = f"${q['value']:,.2f} {unit}" if q and q.get("value") is not None else "N/A"
        observed = q.get("observed") if q else None
        if observed and isinstance(observed, str): observed=datetime.fromisoformat(observed)
        observed_text = observed.astimezone(ZoneInfo("Asia/Tokyo")).strftime("%Y-%m-%d %H:%M JST") if observed and q.get("value") is not None else "N/A"
        table_phase = snapshot.cycle_phase if asset=="BTC" else getattr(m,"phase","N/A")
        confidence = snapshot.confidence if asset=="BTC" else getattr(m,"confidence",None)
        text += f"| {asset} | {price} | {observed_text} | {fmt(q.get('24h_change_pct') if q else None, '%')} | {fmt(q.get('previous_report_pct') if q else None, '%')} | {table_phase} | {fmt(confidence, '%', 1)} |\n"
    text += """

## Bitcoin
"""
    bq=quote_map.get("BTC")
    text += _quote_section("BTC", bq, snapshot.btc_price, "Last UTC Daily Close")
    text += f"""- BTC確定日足：{fmt(snapshot.btc_price, ' USD', 0)}
- フェーズ：{phase}
- Cycle Score{reference}：{fmt(snapshot.cycle_score)} / 100
- Top Risk{reference}：{fmt(snapshot.top_risk_score)} / 100
- Confidence（データ充足度）：{fmt(snapshot.confidence, '%', 1)}
- Global MVRV：{fmt(snapshot.global_mvrv)}
- MVRV Z-Score：{fmt(snapshot.mvrv_zscore)}
- LTH-MVRV：{fmt(snapshot.lth_mvrv)}
- STH-MVRV：{fmt(snapshot.sth_mvrv)}
- LTH Distribution：{fmt(snapshot.lth_distribution)} / 100
- ETF 最新観測フロー：{fmt(snapshot.etf_flow_1d, ' USD')}
- ETF 最新観測日を含む7暦日合計：{fmt(snapshot.etf_flow_7d, ' USD')}
"""
    if core5:
        labels = {"sth_mvrv": "STH-MVRV", "sth_sopr": "STH-SOPR", "lth_mvrv": "LTH-MVRV",
                  "distribution": "LTH Distribution", "sell_side_risk": "Sell-Side Risk 15日SMA"}
        text += "\n## BTC 5-Signal Monitor\n"
        for key, label in labels.items():
            card = core5["cards"][key]
            value = fmt(card["value"] * 100, "%", 3) if key == "sell_side_risk" and card["value"] is not None else fmt(card["value"], digits=3)
            reason = f' · 理由 {card["reason"]}' if card.get("reason") else ""
            text += f'- {label}：{value} · 観測日 {card["date"] or "取得不可"} · Status {card["status"]}{reason}\n'
        text += f'- Short-Term Health：{core5["substates"]["short_term_health"]}\n'
        text += f'- Cycle Heat：{core5["substates"]["cycle_heat"]}\n'
        text += f'- Distribution Pressure：{core5["substates"]["distribution_pressure"]}\n'
        text += f'- BTC 5-Signal State：{core5["state"]}\n'
        text += f'- 判定理由：{" / ".join(core5["reasons"]) or "必要入力を確認済み"}\n'
        if core5["alerts"]:
            text += "\n### Core 5 Alerts\n"
            for alert in core5["alerts"]:
                text += f'- {alert["id"]} · {alert["severity"]} · 観測日 {alert["observation_date"]} · {alert["reason"]}\n'
        text += "\nCore 5は既存スコアと独立した観測レイヤーです。オンチェーン移動は取引所で確認された売却量を意味しません。\n"
    text += """
## 本日の解釈
"""
    if partial:
        text += "主要指標が不足しているため、BTCのサイクル判定を保留します。表示スコアは利用可能なデータのみの参考値です。低いTop Riskを安全の根拠として扱いません。\n"
    else:
        text += f"BTCの現在フェーズは{phase}です。価格、保有者行動、データ充足度を併せて確認してください。\n"
    if stale:
        text += "保存済みデータは期限切れです。数値は集計当時の履歴として表示し、現在の判断には使用しません。\n"
    text += "取得不可の指標は推測・ゼロ補完しません。LTH/STHなどの契約制限は、無料モードでは取得不可として明示します。\n"
    for m in metals:
        text += f"\n## {m.asset.title()}\n"
        text += _quote_section(m.asset.upper(), quote_map.get(m.asset.upper()), m.price, "Previous completed daily close")
        metal_status = phase_status(m.phase, m.confidence, m.date, m.asset,
                                    diagnostics=diagnostics, as_of=as_of)
        hold, mphase = metal_status.partial, metal_status.label
        mreference = "（参考値）" if hold else ""
        text += f"- 保存済み集計日（UTC）：{m.date.isoformat()}\n"
        text += f"- 価格：{fmt(m.price, ' USD')}（現物・先物・ETF代理値の区別はソース参照）\n"
        text += f"- フェーズ：{mphase}\n- Institutional Demand{mreference}：{fmt(m.demand_score)} / 100\n"
        text += f"- Top Risk{mreference}：{fmt(m.top_risk_score)} / 100\n- Dip Quality{mreference}：{fmt(m.dip_quality_score)} / 100\n"
        text += f"- Confidence：{fmt(m.confidence, '%', 1)}\n"
        if hold:
            text += "- 主要データ不足のため、表示スコアは参考値です。\n"
    if diagnostics:
        text += "\n## データの状態\n"
        labels = {"ok": "取得正常", "degraded": "一部取得不可", "error": "主要価格の取得不足"}
        text += f"更新結果：{labels[diagnostics['status']]}\n\n"
        for name, source in diagnostics["sources"].items():
            detail = " / ".join(str(source[k]) for k in ("source", "price_type", "effective_date") if source.get(k))
            text += f"- {name}：{source['status']}" + (f" · {detail}" if detail else "") + "\n"
        text += "\n市場指標はそれぞれの観測日が基準です。CFTCは週次、ETF保有量はスポンサー公表日を使用します。\n"
    text += "\n> 分析支援用の指標です。スコアは将来の値動きや利益を保証しません。\n"
    return text


def _quote_section(asset, q, daily_close, close_label):
    if not q or q.get("value") is None:
        return "- Latest Price：N/A（取得失敗。過去値を今日の価格としてコピーしません）\n"
    observed=q["observed"]
    if isinstance(observed, str): observed=datetime.fromisoformat(observed)
    observed=observed.astimezone(ZoneInfo("Asia/Tokyo")).strftime("%Y-%m-%d %H:%M JST")
    closed = "\n- 新しい価格観測なし。最終取引価格を表示" if q.get("freshness")=="CLOSED_LAST_QUOTE" else ""
    return (f"- Latest：{fmt(q['value'], ' USD' if asset=='BTC' else ' USD / troy oz')}\n- Observed：{observed}\n"
            f"- Source：{q.get('source')}\n- Symbol / Type：{q.get('symbol')} / {q.get('price_type')}\n"
            f"- Freshness：{q.get('freshness')}（age {fmt(q.get('age_minutes'), ' min', 1)}）\n"
            f"- Market State：{q.get('market_state')}\n- {close_label}：{fmt(daily_close, ' USD')}\n{closed}\n")


def generate_report(snapshot, output_root: Path | None = None, *, metals=(), diagnostics=None, core5=None, quotes=()) -> Path:
    root = output_root or ROOT / "reports"
    archive = root / "archive"
    archive.mkdir(parents=True, exist_ok=True)
    text = report_text(snapshot, metals=metals, diagnostics=diagnostics, core5=core5, quotes=quotes)
    latest = root / "latest.md"
    latest.write_text(text, encoding="utf-8")
    (archive / f"{snapshot.date}.md").write_text(text, encoding="utf-8")
    return latest
