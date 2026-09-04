"""Bitcoin On-Chain Cycle Dashboard (Japanese-first Streamlit UI)."""
from datetime import datetime, timezone

import pandas as pd
import plotly.express as px
import streamlit as st

from config.settings import get_settings
from collectors.cftc import scheduled_publication_date
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
        snapshots = repo.snapshots(); metrics = repo.metrics(); metals = repo.metal_snapshots(); etfs = repo.etf_holdings()
        cot = repo.cot("gold") + repo.cot("silver")
        serialize = lambda rows: [{c.name: getattr(x, c.name) for c in x.__table__.columns} for x in rows]
        return serialize(snapshots), serialize(metrics), serialize(metals), serialize(cot), serialize(etfs)


def shown(value, fmt=".1f"):
    return "取得不可" if value is None or pd.isna(value) else format(value, fmt)


def confidence_label(value):
    if value is None or value < 40: return "データ不足 / Insufficient"
    if value < 60: return "信頼度低 / Low"
    if value < 80: return "中程度 / Moderate"
    return "高 / High"


def safe_phase(phase, confidence):
    return "判定保留 / PARTIAL" if confidence is None or confidence < 50 or phase == "PARTIAL" else f"{phase} / {PHASE_JA.get(phase, phase)}"


snapshots, metrics, metal_snapshots, cot, etfs = load_data(); latest = snapshots[-1] if snapshots else None
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
        cols[1].metric("現在", safe_phase(latest["cycle_phase"], latest["confidence"]))
        reference = " 参考値" if latest["confidence"] < 50 else ""
        cols[2].metric("Cycle Score", f'{shown(latest["cycle_score"])} / 100{reference}')
        cols[3].metric("Top Risk", f'{shown(latest["top_risk_score"])} / 100{reference}')
        st.metric("Confidence（主要データ充足度）", f'{shown(latest["confidence"])}% · {confidence_label(latest["confidence"])}')
        if latest["confidence"] < 50: st.error("判定保留：オンチェーン主要指標など、正式判定に必要なデータが不足しています。")
        st.subheader("今日の重要変化")
        previous = snapshots[-2] if len(snapshots) > 1 else None
        if previous and previous["cycle_phase"] != latest["cycle_phase"]: st.warning(f'{previous["cycle_phase"]} → {latest["cycle_phase"]}')
        else: st.info("本日の重要なレジーム変化はありません")
        st.caption("スコアは利用可能な実測値のみを再ウェイトして算出。低いConfidenceでは断定的に解釈しないでください。")
    latest_metals = {x["asset"]: x for x in metal_snapshots if x["date"] == max((m["date"] for m in metal_snapshots), default=None)}
    st.subheader("3資産クイック比較")
    for col, asset in zip(st.columns(3), ("BTC", "GOLD", "SILVER")):
        if asset == "BTC" and latest: col.markdown(f"**BTC**  \nPrice {shown(latest['btc_price'])} · Cycle {shown(latest['cycle_score'])} · Top {shown(latest['top_risk_score'])}  \n**{safe_phase(latest['cycle_phase'], latest['confidence'])}** · Confidence {shown(latest['confidence'])}%")
        elif asset in latest_metals:
            m=latest_metals[asset]; col.markdown(f"**{asset}**  \nPrice {shown(m['price'])} · Demand {shown(m['demand_score'])} · Top {shown(m['top_risk_score'])} · Dip {shown(m['dip_quality_score'])}  \n**{safe_phase(m['phase'], m['confidence'])}** · Confidence {shown(m['confidence'])}%")

metric_df = pd.DataFrame(metrics)
with tabs[1]:
    btc_prices = metric_df[(metric_df.metric_name == "btc_price_usd") & metric_df.value.notna()].sort_values("date") if not metric_df.empty else pd.DataFrame()
    if not btc_prices.empty:
        series = btc_prices.set_index("date").value.astype(float)
        values = {"Price": series.iloc[-1], "7D": series.pct_change(7).iloc[-1] * 100,
                  "30D": series.pct_change(30).iloc[-1] * 100, "90D": series.pct_change(90).iloc[-1] * 100,
                  "50DMA": series.rolling(50).mean().iloc[-1], "100DMA": series.rolling(100).mean().iloc[-1],
                  "200DMA": series.rolling(200).mean().iloc[-1]}
        for col, (label, value) in zip(st.columns(7), values.items()): col.metric(label, shown(value))
        st.caption(f"Price source: {btc_prices.iloc[-1].source} · daily close/current candle · freshness: daily")
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
            labels=(("Price",m["price"]),("Institutional Demand (参考値)" if m["confidence"]<50 else "Institutional Demand",m["demand_score"]),("Top Risk (参考値)" if m["confidence"]<50 else "Top Risk",m["top_risk_score"]),("Dip Quality",m["dip_quality_score"]),("Phase",safe_phase(m["phase"],m["confidence"])),("Confidence",f'{shown(m["confidence"])}% · {confidence_label(m["confidence"])}'))
            for col,(label,value) in zip(st.columns(6),labels): col.metric(label, shown(value) if isinstance(value,(int,float)) else value)
            if m["price"] is None: st.warning("Dip Quality: N/A — Price unavailable。CFTCが取得済みでも価格不足のため正式判定を保留します。")
        price_rows = metric_df[(metric_df.metric_name == f"{asset.lower()}_price_usd") & metric_df.value.notna()].sort_values(["date", "fetched_at"]).drop_duplicates("date", keep="last") if not metric_df.empty else pd.DataFrame()
        if not price_rows.empty:
            ps = price_rows.set_index("date").value.astype(float)
            stats = {"7D %": ps.pct_change(7).iloc[-1]*100, "30D %": ps.pct_change(30).iloc[-1]*100,
                     "90D %": ps.pct_change(90).iloc[-1]*100, "50DMA": ps.rolling(50).mean().iloc[-1],
                     "200DMA": ps.rolling(200).mean().iloc[-1], "Drawdown %": (ps.iloc[-1]/ps.cummax().iloc[-1]-1)*100,
                     "ATH distance %": (ps.iloc[-1]/ps.max()-1)*100}
            for col,(label,value) in zip(st.columns(7),stats.items()): col.metric(label, shown(value))
            latest_price = price_rows.iloc[-1]
            st.markdown(f"**Price Source:** {latest_price.source}　 **Price Type:** {latest_price.price_type or 'N/A'}")
        asset_cot=[x for x in cot if x["asset"]==asset]; cot_df=pd.DataFrame(asset_cot)
        if asset_cot:
            last=max(x["report_date"] for x in asset_cot); published=scheduled_publication_date(last)
            st.info(f"CFTC COTは週次（火曜時点、通常金曜公表）。Position date: {last} · Published (scheduled): {published} · Position age: {(datetime.now(timezone.utc).date()-last).days} days。日次価格とは鮮度基準が異なります。")
            mm=cot_df[cot_df.category=="managed_money"]
            st.plotly_chart(px.line(mm,x="report_date",y=["long","short","net"],title=f"{asset} Managed Money / Net"), width="stretch")
            st.plotly_chart(px.line(mm,x="report_date",y="open_interest",title="Open Interest"), width="stretch")
        st.caption("Price↑+OI↑: 新規参加 / Price↑+OI↓: short covering / Price↓+OI↑: 新規short / Price↓+OI↓: liquidation")
        st.warning("ETF holdings/flow は公式構造化データを取得できない場合 Unavailable。holdings changeを実測flowとして表示しません。")
        # Parse/schema diagnostics remain visible in System, but must not make an
        # unavailable sponsor snapshot look usable to the UI or scoring status.
        asset_etfs = pd.DataFrame([x for x in etfs if x["asset"] == asset and x["status"] == "OK"])
        if m:
            demand_state = "Strong Buying" if (m["demand_score"] or 0) >= 75 else "Moderate Buying" if (m["demand_score"] or 0) >= 55 else "Neutral / Weak"
            risk_state = "Elevated" if (m["top_risk_score"] or 0) >= 60 else "Normal"
            st.markdown(f"**Demand State:** {demand_state}　 **Positioning Risk:** {risk_state}")
            missing = []
            if m["price"] is None: missing.append("Price")
            if asset_etfs.empty: missing.append("ETF holdings")
            if not asset_cot: missing.extend(["CFTC Managed Money", "Open Interest"])
            st.caption("不足データ / Missing: " + (", ".join(missing) if missing else "なし。スコアは実測入力のみ。"))
        expected_funds = {"GOLD": {"GLD", "IAU"}, "SILVER": {"SLV"}}[asset]
        available_funds = set(asset_etfs.fund) if not asset_etfs.empty else set()
        etf_status = "OK" if available_funds == expected_funds else "PARTIAL" if available_funds else "N/A"
        st.markdown(f"**ETF Data:** {', '.join(sorted(available_funds)) or 'N/A'}　 **ETF Status:** {etf_status}")
        st.subheader("ETF (official sponsor data)")
        if asset_etfs.empty: st.info("Holdings / shares outstanding / flow: N/A")
        else: st.dataframe(asset_etfs.groupby("fund").tail(1)[["fund","effective_date","shares_outstanding","physical_holdings","holdings_unit","net_assets","flow","flow_status","status","fetched_at","source"]], hide_index=True, width="stretch")
with tabs[4]:
    st.header("BTC / Gold / Silver Compare")
    frame=pd.DataFrame(metal_snapshots)
    if frame.empty: st.info("Gold/Silverデータなし")
    else: st.dataframe(frame[["asset","price","demand_score","top_risk_score","dip_quality_score","phase","confidence","date"]].groupby("asset").tail(1),hide_index=True,width="stretch")
with tabs[5]:
    st.header("History")
    frame = pd.DataFrame(snapshots)
    if frame.empty: st.info("履歴なし")
    else:
        st.plotly_chart(px.line(frame, x="date", y=["cycle_score", "top_risk_score"], title="Cycle / Top Risk"), width="stretch")
        changes = frame[frame.cycle_phase.ne(frame.cycle_phase.shift())][["date", "cycle_phase"]]
        st.subheader("Phase History"); st.dataframe(changes, hide_index=True, width="stretch")
with tabs[6]:
    st.header("System / Data Provenance")
    st.write("モード:", "Glassnode接続" if get_settings().glassnode_api_key else "FREE MODE（Glassnode API未接続）")
    if not metric_df.empty: st.dataframe(metric_df[["date", "metric_name", "value", "source", "status", "fetched_at"]].sort_values("fetched_at", ascending=False), hide_index=True, width="stretch")
    st.subheader("Gold / Silver sources")
    st.write("CFTC Public Reporting (official):", "OK" if cot else "UNAVAILABLE")
    st.write("ETF official sponsor feeds:", "OK" if etfs else "UNAVAILABLE（取得項目を推計しません）")
    if etfs:
        st.dataframe(pd.DataFrame(etfs)[["fund","asset","source","status","effective_date","fetched_at","error"]].sort_values("fetched_at", ascending=False), hide_index=True, width="stretch")
    st.subheader("Data Status / Freshness SLA")
    statuses=[]
    for asset in ("BTC","GOLD","SILVER"):
        price_name="btc_price_usd" if asset=="BTC" else f"{asset.lower()}_price_usd"
        pr=metric_df[(metric_df.metric_name==price_name) & metric_df.value.notna()] if not metric_df.empty else pd.DataFrame()
        statuses.append({"asset":asset,"Price":"OK" if not pr.empty else "ERROR","CFTC":"N/A" if asset=="BTC" else ("OK" if any(x["asset"]==asset for x in cot) else "ERROR"),
            "ETF":"OK" if any(x["asset"]==asset and x["status"]=="OK" for x in etfs) else "N/A","On-chain":"PARTIAL" if asset=="BTC" and latest and latest["confidence"]<100 else ("OK" if asset=="BTC" else "N/A"),"Price SLA":"daily","CFTC SLA":"weekly" if asset!="BTC" else "N/A"})
    st.dataframe(pd.DataFrame(statuses),hide_index=True,width="stretch")
    st.caption(f"表示時刻: {datetime.now(timezone.utc).isoformat()} · UI cache TTL: {get_settings().cache_ttl_seconds}秒")
