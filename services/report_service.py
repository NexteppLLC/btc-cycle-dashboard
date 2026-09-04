"""Japanese daily report generation; missing remains explicitly unavailable."""
from pathlib import Path
from config.settings import ROOT


def fmt(value, suffix="", digits=2): return "取得不可" if value is None else f"{value:,.{digits}f}{suffix}"


def generate_report(snapshot, output_root: Path | None = None) -> Path:
    root = output_root or ROOT / "reports"; archive = root / "archive"; archive.mkdir(parents=True, exist_ok=True)
    text = f"""# 【BTC On-Chain Daily Report】

日付：{snapshot.date.isoformat()}

- BTC：${fmt(snapshot.btc_price, digits=0)}
- Cycle：{snapshot.cycle_phase}
- Cycle Score：{fmt(snapshot.cycle_score)} / 100
- Top Risk：{fmt(snapshot.top_risk_score)} / 100
- Confidence：{fmt(snapshot.confidence, '%', 1)}

## LTH
- LTH-MVRV：{fmt(snapshot.lth_mvrv)}
- Distribution：{fmt(snapshot.lth_distribution)} / 100

## STH
- STH-MVRV：{fmt(snapshot.sth_mvrv)}

## ETF
- 1D：{fmt(snapshot.etf_flow_1d, ' USD')}
- 7D：{fmt(snapshot.etf_flow_7d, ' USD')}

## 本日の結論
フェーズは **{snapshot.cycle_phase}**。取得不可の値を推計・ゼロ補完していません。Confidenceを併せて解釈してください。

## 警戒ポイント
- LTH Distribution 60超
- Top Risk 70超
- STH-MVRV 1割れ
- ETF 7日累計マイナス転換

> ※本ツールは分析支援用であり、投資助言ではありません。
"""
    latest = root / "latest.md"; latest.write_text(text, encoding="utf-8"); (archive / f"{snapshot.date}.md").write_text(text, encoding="utf-8")
    return latest
