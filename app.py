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
        snapshots = repo.snapshots(); metrics = repo.metrics(); metals = repo.metal_snapshots()
        cot = repo.cot("gold") + repo.cot("silver")
        serialize = lambda rows: [{c.name: getattr(x, c.name) for c in x.__table__.columns} for x in rows]
        return serialize(snapshots), serialize(metrics), serialize(metals), serialize(cot)


def shown(value, fmt=".1f"):
    return "取得不可" if value is None or pd.isna(value) else format(value, fmt)


snapshots, metrics, metal_snapshots, cot = load_data(); latest = snapshots[-1] if snapshots else None
st.title("₿ BTC MARKET CYCLE")
st.caption("価格・オンチェーン・保有者行動・ETF需要を複合評価する分析支援ツール")
st.warning("本ダッシュボードは金融・投資助言ではありません。欠損データを0や推測値で補完しません。")

tabs = st.tabs(["Overview", "Bitcoin", "Gold", "Silver", "Compare", "History", "System"])
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
    latest_metals = {x["asset"]: x for x in metal_snapshots if x["date"] == max((m["date"] for m in metal_snapshots), default=None)}
    st.subheader("3資産クイック比較")
    for col, asset in zip(st.columns(3), ("BTC", "GOLD", "SILVER")):
        if asset == "BTC" and latest: col.markdown(f"**BTC**  \nCycle {shown(latest['cycle_score'])} · Top {shown(latest['top_risk_score'])}  \n`{latest['cycle_phase']}`")
        elif asset in latest_metals:
            m=latest_metals[asset]; col.markdown(f"**{asset}**  \nDemand {shown(m['demand_score'])} · Top {shown(m['top_risk_score'])} · Dip {shown(m['dip_quality_score'])}  \n`{m['phase']}`")

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
for tab, asset in ((tabs[2], "GOLD"), (tabs[3], "SILVER")):
    with tab:
        st.header(f"{asset.title()} Institutional Flow")
        rows=[x for x in metal_snapshots if x["asset"]==asset]; m=rows[-1] if rows else None
        if not m: st.info("取得済みデータなし / Unavailable")
        else:
            labels=(("Price",m["price"]),("Institutional Demand",m["demand_score"]),("Top Risk",m["top_risk_score"]),("Dip Quality",m["dip_quality_score"]),("Phase",m["phase"]),("Confidence",m["confidence"]))
            for col,(label,value) in zip(st.columns(6),labels): col.metric(label, shown(value) if isinstance(value,(int,float)) else value)
        asset_cot=[x for x in cot if x["asset"]==asset]; cot_df=pd.DataFrame(asset_cot)
        if asset_cot:
            last=max(x["report_date"] for x in asset_cot); st.info(f"CFTC COTは週次（火曜時点、金曜公表）。Last COT report: {last} · Next expected update: Friday · Age: {(datetime.now(timezone.utc).date()-last).days} days。日次価格とはタイムスタンプが異なります。")
            mm=cot_df[cot_df.category=="managed_money"]
            st.plotly_chart(px.line(mm,x="report_date",y=["long","short","net"],title=f"{asset} Managed Money / Net"),use_container_width=True)
            st.plotly_chart(px.line(mm,x="report_date",y="open_interest",title="Open Interest"),use_container_width=True)
        st.caption("Price↑+OI↑: 新規参加 / Price↑+OI↓: short covering / Price↓+OI↑: 新規short / Price↓+OI↓: liquidation")
        st.warning("ETF holdings/flow は公式構造化データを取得できない場合 Unavailable。holdings changeを実測flowとして表示しません。")
with tabs[4]:
    st.header("BTC / Gold / Silver Compare")
    frame=pd.DataFrame(metal_snapshots)
    if frame.empty: st.info("Gold/Silverデータなし")
    else: st.dataframe(frame[["asset","price","demand_score","top_risk_score","dip_quality_score","phase","confidence","date"]].groupby("asset").tail(1),hide_index=True,use_container_width=True)
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
    st.subheader("Gold / Silver sources")
    st.write("CFTC Public Reporting (official):", "OK" if cot else "UNAVAILABLE")
    st.write("ETF provider structured feeds:", "UNAVAILABLE（未設定。値は推計しません）")
    st.caption(f"表示時刻: {datetime.now(timezone.utc).isoformat()} · UI cache TTL: {get_settings().cache_ttl_seconds}秒")
