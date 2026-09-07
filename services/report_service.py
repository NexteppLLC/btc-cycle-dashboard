"""Japanese daily report; partial/stale inputs never imply a safe market."""
from math import isfinite
from pathlib import Path
from datetime import date, datetime, timezone

from config.settings import ROOT
from scoring.regime import PHASE_JA


def fmt(value, suffix="", digits=2):
    return "取得不可" if value is None or not isfinite(float(value)) else f"{value:,.{digits}f}{suffix}"


def report_text(snapshot, *, metals=(), diagnostics=None) -> str:
    as_of = date.fromisoformat(diagnostics["as_of"]) if diagnostics else datetime.now(timezone.utc).date()
    stale = (as_of - snapshot.date).days > 3
    price_missing = diagnostics and diagnostics["sources"].get("btc_price_usd", {}).get("status") != "OK"
    partial = stale or price_missing or snapshot.cycle_phase in ("PARTIAL", "UNKNOWN") or snapshot.confidence < 50
    reference = "（参考値）" if partial else ""
    phase = "判定保留 / PARTIAL" if partial else f"{snapshot.cycle_phase} / {PHASE_JA.get(snapshot.cycle_phase, snapshot.cycle_phase)}"
    text = f"""# BTC / Gold / Silver 日次レポート

保存済み集計日（UTC）：{snapshot.date.isoformat()}

## Bitcoin
- BTC：{fmt(snapshot.btc_price, ' USD', 0)}
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
- ETF 直近7暦日合計：{fmt(snapshot.etf_flow_7d, ' USD')}

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
        price_missing = diagnostics and diagnostics["sources"].get(f"{m.asset.lower()}_price_usd", {}).get("status") != "OK"
        hold = (as_of - m.date).days > 3 or price_missing or m.phase in ("PARTIAL", "UNKNOWN") or m.confidence < 50
        mphase = "判定保留 / PARTIAL" if hold else f"{m.phase} / {PHASE_JA.get(m.phase, m.phase)}"
        text += f"- 保存済み集計日（UTC）：{m.date.isoformat()}\n"
        text += f"- 価格：{fmt(m.price, ' USD')}（現物・先物・ETF代理値の区別はソース参照）\n"
        text += f"- フェーズ：{mphase}\n- Institutional Demand：{fmt(m.demand_score)} / 100\n"
        text += f"- Top Risk：{fmt(m.top_risk_score)} / 100\n- Dip Quality：{fmt(m.dip_quality_score)} / 100\n"
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


def generate_report(snapshot, output_root: Path | None = None, *, metals=(), diagnostics=None) -> Path:
    root = output_root or ROOT / "reports"
    archive = root / "archive"
    archive.mkdir(parents=True, exist_ok=True)
    text = report_text(snapshot, metals=metals, diagnostics=diagnostics)
    latest = root / "latest.md"
    latest.write_text(text, encoding="utf-8")
    (archive / f"{snapshot.date}.md").write_text(text, encoding="utf-8")
    return latest
