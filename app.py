"""Bitcoin On-Chain Cycle Dashboard (Japanese-first Streamlit UI)."""
from datetime import datetime, timezone

import pandas as pd
import plotly.express as px
import streamlit as st

from config.settings import get_settings
from database.repository import Repository
from database.session import create_schema, session_scope
from scoring.regime import PHASE_JA

st.set_page_config(page_title="BTC Market Cycle", page_icon="₿", layout="wide")
st.markdown("""<style>.stApp{background:#07111f;color:#edf2f7}.kpi{background:#111e30;border:1px solid #263850;border-radius:12px;padding:18px}.muted{color:#91a4ba}.status{font-size:1.15rem;font-weight:700}</style>""", unsafe_allow_html=True)
create_schema()


@st.cache_data(ttl=get_settings().cache_ttl_seconds)
def load_data():
    with session_scope() as session:
        repo = Repository(session)
        snapshots = repo.snapshots(); metrics = repo.metrics()
        return ([{c.name: getattr(x, c.name) for c in x.__table__.columns} for x in snapshots], [{c.name: getattr(x, c.name) for c in x.__table__.columns} for x in metrics])


def shown(value, fmt=".1f"):
    return "取得不可" if value is None or pd.isna(value) else format(value, fmt)


snapshots, metrics = load_data(); latest = snapshots[-1] if snapshots else None
st.title("₿ BTC MARKET CYCLE")
st.caption("価格・オンチェーン・保有者行動・ETF需要を複合評価する分析支援ツール")
st.warning("本ダッシュボードは金融・投資助言ではありません。欠損データを0や推測値で補完しません。")

tabs = st.tabs(["Overview", "MVRV", "Holders", "ETF", "Technical", "History", "System"])
with tabs[0]:
    if not latest:
        st.info("保存済みデータがありません。`python scripts/update_data.py` を実行してください。")
    else:
        cols = st.columns(4)
        cols[0].metric("Bitcoin", "取得不可" if latest["btc_price"] is None else f'${latest["btc_price"]:,.0f}')
        cols[1].metric("現在", f'{latest["cycle_phase"]} / {PHASE_JA.get(latest["cycle_phase"], "データ不足")}')
        cols[2].metric("Cycle Score", f'{shown(latest["cycle_score"])} / 100')
        cols[3].metric("Top Risk", f'{shown(latest["top_risk_score"])} / 100')
        st.metric("Confidence（データ充足・鮮度）", f'{shown(latest["confidence"])}%')
        st.subheader("今日の重要変化")
        previous = snapshots[-2] if len(snapshots) > 1 else None
        if previous and previous["cycle_phase"] != latest["cycle_phase"]: st.warning(f'{previous["cycle_phase"]} → {latest["cycle_phase"]}')
        else: st.info("本日の重要なレジーム変化はありません")
        st.caption("スコアは利用可能な実測値のみを再ウェイトして算出。低いConfidenceでは断定的に解釈しないでください。")

metric_df = pd.DataFrame(metrics)
with tabs[1]:
    st.header("MVRV / Cost Basis")
    names = ["global_mvrv", "mvrv_zscore", "lth_mvrv", "sth_mvrv", "realized_price", "lth_realized_price", "sth_realized_price"]
    for col, name in zip(st.columns(4), names):
        rows = metric_df[metric_df.metric_name == name] if not metric_df.empty else pd.DataFrame()
        if rows.empty: col.metric(name, "Glassnode API未接続 / 取得不可")
        else:
            row = rows.iloc[-1]; col.metric(name, shown(row.value)); col.caption(f'{row.source} · {row.fetched_at}')
    st.caption("期間: 30D / 90D / 1Y / 2Y / 4Y / ALL（保存済み履歴に応じて表示）")
with tabs[2]:
    st.header("Holder Behaviour")
    st.metric("LTH Distribution Score", "取得不可" if not latest else f'{shown(latest["lth_distribution"])} / 100')
    st.info("Glassnode契約指標がない場合、LTH/STH値は推計せず『取得不可』です。利用可能な構成要素だけを再ウェイトしConfidenceを低下させます。")
with tabs[3]:
    st.header("米国現物Bitcoin ETF Flow")
    flows = metric_df[(metric_df.metric_name == "etf_flow_usd") & metric_df.value.notna()] if not metric_df.empty else pd.DataFrame()
    if flows.empty: st.info("Pending：構造化ETF CSV未設定、または当日データ未公表です。前回値をコピーしません。")
    else: st.plotly_chart(px.bar(flows, x="date", y="value", title="ETF日次純流入 (USD)"), use_container_width=True)
with tabs[4]:
    st.header("Technical")
    prices = metric_df[(metric_df.metric_name == "btc_price_usd") & metric_df.value.notna()] if not metric_df.empty else pd.DataFrame()
    if prices.empty: st.info("BTC価格履歴がありません。")
    else: st.plotly_chart(px.line(prices, x="date", y="value", title="BTC/USD（実測取得値）"), use_container_width=True)
with tabs[5]:
    st.header("History")
    frame = pd.DataFrame(snapshots)
    if frame.empty: st.info("履歴なし")
    else:
        st.plotly_chart(px.line(frame, x="date", y=["cycle_score", "top_risk_score"], title="Cycle / Top Risk"), use_container_width=True)
        changes = frame[frame.cycle_phase.ne(frame.cycle_phase.shift())][["date", "cycle_phase"]]
        st.subheader("Phase History"); st.dataframe(changes, hide_index=True, use_container_width=True)
with tabs[6]:
    st.header("System / Data Provenance")
    st.write("モード:", "Glassnode接続" if get_settings().glassnode_api_key else "FREE MODE（Glassnode API未接続）")
    if not metric_df.empty: st.dataframe(metric_df[["date", "metric_name", "value", "source", "status", "fetched_at"]].sort_values("fetched_at", ascending=False), hide_index=True, use_container_width=True)
    st.caption(f"表示時刻: {datetime.now(timezone.utc).isoformat()} · UI cache TTL: {get_settings().cache_ttl_seconds}秒")

