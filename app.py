"""Bitcoin On-Chain Cycle Dashboard (Japanese-first Streamlit UI)."""
from datetime import datetime, timezone
from types import SimpleNamespace

import pandas as pd
import plotly.express as px
import streamlit as st

from config.settings import get_settings
from collectors.cftc import scheduled_publication_date
from database.repository import Repository
from database.session import create_schema, session_scope
from scoring.regime import PHASE_JA
from indicators.holders import sth_state
from indicators.normalization import change_summary, multi_horizon_stats
from services.data_quality import current_metric_row, metric_current, metric_series, selected_metric_rows
from services.health_service import build_diagnostics
from services.report_service import report_text

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


def safe_phase(phase, confidence, day=None, asset="btc"):
    source_missing = quality["sources"].get(f"{asset.lower()}_price_usd", {}).get("status") != "OK"
    if asset.lower() != "btc":
        source_missing = source_missing or quality["sources"].get(f"{asset.lower()}_cot", {}).get("status") != "OK"
    stale = day is not None and (datetime.now(timezone.utc).date() - day).days > 3
    return "判定保留 / PARTIAL" if stale or source_missing or confidence is None or confidence < 50 or phase in ("PARTIAL", "UNKNOWN") else f"{phase} / {PHASE_JA.get(phase, phase)}"


def metric_grid(items, columns=4):
    """Render every card, wrapping rows rather than truncating zip to columns."""
    items = list(items)
    for start in range(0, len(items), columns):
        for col, (label, value) in zip(st.columns(columns), items[start:start + columns]):
            col.metric(label, value if isinstance(value, str) else shown(value))


def latest_fund_rows(asset=None, fresh_only=False):
    frame = pd.DataFrame([x for x in etfs if x["status"] == "OK" and (asset is None or x["asset"] == asset)])
    if frame.empty:
        return frame
    frame = frame.sort_values(["date", "fetched_at"]).groupby("fund").tail(1)
    if fresh_only:
        age = (pd.Timestamp.now(tz="UTC").normalize() - pd.to_datetime(frame.effective_date, utc=True)).dt.days
        frame = frame[age.between(0, 5)]
    return frame


snapshots, metrics, metal_snapshots, cot, etfs = load_data(); latest = snapshots[-1] if snapshots else None
quality = build_diagnostics(metrics, cot, etfs)
with st.sidebar:
    st.header("データ更新")
    if st.button("最新の保存データを表示", key="reload_data"):
        load_data.clear()
        st.rerun()
    if st.button("データを取得・更新", key="collect_data"):
        with st.spinner("価格・オンチェーン・ETF・CFTCを取得しています…"):
            try:
                from services.update_service import run_update
                from services.report_service import generate_report
                result = run_update()
                with session_scope() as session:
                    repo = Repository(session)
                    updated_quality = build_diagnostics(repo.metrics(), repo.cot("gold") + repo.cot("silver"), repo.etf_holdings())
                generate_report(result["snapshot"], metals=result["metals"], diagnostics=updated_quality)
                load_data.clear()
                st.rerun()
            except Exception as exc:
                st.error(f"更新できませんでした（{type(exc).__name__}）。時間をおいて再実行してください。")
    st.caption("自動更新：毎日07:45（日本時間）。取得先の応答により数分かかることがあります。")
    if latest:
        st.caption(f"保存済み集計日（UTC）：{latest['date']}")
        report_metals = {x["asset"]: x for x in metal_snapshots}
        st.download_button("日次レポートを保存", report_text(SimpleNamespace(**latest),
                           metals=[SimpleNamespace(**m) for m in report_metals.values()], diagnostics=quality),
                           file_name=f"market-cycle-{latest['date']}.md", mime="text/markdown")
st.title("₿ BTC MARKET CYCLE")
st.caption("価格・オンチェーン・保有者行動・ETF需要を複合評価する分析支援ツール")
st.warning("本ダッシュボードは金融・投資助言ではありません。欠損データを0や推測値で補完しません。")
if latest and (datetime.now(timezone.utc).date() - latest["date"]).days > 3:
    st.error("保存済みの判定が古くなっています。履歴として表示しています。データを取得・更新してください。")
if quality["essential_failures"]:
    st.warning("一部の価格が未取得または期限切れです。Systemで観測日と取得状態を確認できます。")

tabs = st.tabs(["Overview", "Bitcoin", "Gold", "Silver", "Compare", "History", "System"])
with tabs[0]:
    if not latest:
        st.info("保存済みデータがありません。左側の「データを取得・更新」を押してください。")
    else:
        cols = st.columns(4)
        cols[0].metric("Bitcoin", "取得不可" if latest["btc_price"] is None else f'${latest["btc_price"]:,.0f}')
        cols[1].metric("現在", safe_phase(latest["cycle_phase"], latest["confidence"], latest["date"]))
        reference = " 参考値" if latest["confidence"] < 50 else ""
        cols[2].metric("Cycle Score", f'{shown(latest["cycle_score"])} / 100{reference}')
        cols[3].metric("Top Risk", f'{shown(latest["top_risk_score"])} / 100{reference}')
        st.metric("Confidence（主要データ充足度）", f'{shown(latest["confidence"])}% · {confidence_label(latest["confidence"])}')
        if latest["confidence"] < 50: st.error("判定保留：オンチェーン主要指標など、正式判定に必要なデータが不足しています。")
        st.subheader("今日の重要変化")
        previous = snapshots[-2] if len(snapshots) > 1 else None
        if previous and previous["cycle_phase"] != latest["cycle_phase"]: st.warning(f'{previous["cycle_phase"]} → {latest["cycle_phase"]}')
        elif latest["cycle_phase"] in ("PARTIAL", "UNKNOWN"): st.info("主要データ不足のため、レジーム変化も判定保留です。")
        else: st.info("保存済みの前回判定から変更はありません")
        st.caption("スコアは利用可能な実測値のみを再ウェイトして算出。低いConfidenceでは断定的に解釈しないでください。")
    latest_metals = {x["asset"]: x for x in metal_snapshots if x["date"] == max((m["date"] for m in metal_snapshots), default=None)}
    st.subheader("3資産クイック比較")
    for col, asset in zip(st.columns(3), ("BTC", "GOLD", "SILVER")):
        if asset == "BTC" and latest: col.markdown(f"**BTC**  \nPrice {shown(latest['btc_price'])} · Cycle {shown(latest['cycle_score'])} · Top {shown(latest['top_risk_score'])}  \n**{safe_phase(latest['cycle_phase'], latest['confidence'], latest['date'])}** · Confidence {shown(latest['confidence'])}%")
        elif asset in latest_metals:
            m=latest_metals[asset]; col.markdown(f"**{asset}**  \nPrice {shown(m['price'])} · Demand {shown(m['demand_score'])} · Top {shown(m['top_risk_score'])} · Dip {shown(m['dip_quality_score'])}  \n**{safe_phase(m['phase'], m['confidence'], m['date'], m['asset'])}** · Confidence {shown(m['confidence'])}%")

metric_df = pd.DataFrame(metrics)
with tabs[1]:
    btc_prices = pd.DataFrame(selected_metric_rows(metrics, "btc_price_usd"))
    if not btc_prices.empty:
        series = metric_series(metrics, "btc_price_usd")
        series.index = pd.to_datetime(series.index)
        series = series.asfreq("D")
        values = {"Price": metric_current(metrics, "btc_price_usd"), "7D": series.pct_change(7, fill_method=None).iloc[-1] * 100,
                  "30D": series.pct_change(30, fill_method=None).iloc[-1] * 100, "90D": series.pct_change(90, fill_method=None).iloc[-1] * 100,
                  "50DMA": series.rolling(50).mean().iloc[-1], "100DMA": series.rolling(100).mean().iloc[-1],
                  "200DMA": series.rolling(200).mean().iloc[-1]}
        if current_metric_row(metrics, "btc_price_usd") is None:
            values = dict.fromkeys(values)
        for col, (label, value) in zip(st.columns(7), values.items()): col.metric(label, shown(value))
        st.caption(f"Price source: {btc_prices.iloc[-1].source} · 最終観測日: {btc_prices.iloc[-1].date} · 日足終値")
    st.header("MVRV / Cost Basis")
    if latest:
        hero = (("LTH-MVRV", latest["lth_mvrv"]), ("STH-MVRV", latest["sth_mvrv"]),
                ("LTH Distribution", latest["lth_distribution"]), ("MVRV Z-Score", latest["mvrv_zscore"]),
                ("Cycle Score", latest["cycle_score"]), ("Top Risk", latest["top_risk_score"]),
                ("Phase", safe_phase(latest["cycle_phase"], latest["confidence"], latest["date"])),
                ("Confidence", f'{shown(latest["confidence"])}%'))
        metric_grid(hero)
    names = ["global_mvrv", "lth_mvrv", "sth_mvrv", "mvrv_zscore"]
    for col, name in zip(st.columns(4), names):
        rows = pd.DataFrame(selected_metric_rows(metrics, name))
        if rows.empty: col.metric(name, "N/A")
        else:
            rows = rows.sort_values(["date", "fetched_at"]); row = rows.iloc[-1]
            values = metric_series(metrics, name)
            values.index = pd.to_datetime(values.index)
            values = values.asfreq("D")
            summary = change_summary(values); stats = multi_horizon_stats(values)
            if current_metric_row(metrics, name) is None:
                summary = dict.fromkeys(summary)
                stats = dict.fromkeys(stats)
            col.metric(name, shown(metric_current(metrics, name)), delta=f'1D {shown(summary["daily_change"], ".3f")} / 7D {shown(summary["change_7d"], ".3f")}')
            freshness = "OK" if current_metric_row(metrics, name) is not None else "STALE / 取得不可"
            col.caption(f'{row.source} · {freshness} · 観測日 {row.date} · 取得 {row.fetched_at} · 52W pct {shown(stats["percentile_52w"], ".2f")}')
    period = st.selectbox("Realized Price Zones期間", ["90D", "1Y", "2Y", "4Y", "ALL"], index=1)
    period_days = {"90D":90, "1Y":365, "2Y":730, "4Y":1461, "ALL":None}[period]
    cost_names = {"btc_price_usd":"BTC Price", "realized_price":"Global Realized Price",
                  "lth_realized_price":"LTH Realized Price", "sth_realized_price":"STH Realized Price"}
    cost = pd.DataFrame([row for name in cost_names for row in selected_metric_rows(metrics, name)])
    if not cost.empty:
        cost = cost.sort_values(["date","fetched_at"]).drop_duplicates(["date","metric_name"],keep="last")
        if period_days: cost = cost[cost.date >= (pd.Timestamp.utcnow().date()-pd.Timedelta(days=period_days))]
        chart = cost.pivot(index="date",columns="metric_name",values="value").rename(columns=cost_names)
        st.plotly_chart(px.line(chart, title="BTC Price / Realized Price Zones"), width="stretch")
    st.subheader("Holder Behaviour")
    holder_names = ["lth_sopr","sth_sopr","lth_spent_volume","sth_spent_volume","lth_supply","sth_supply","cdd"]
    holder_values = {}
    for name in holder_names:
        holder_values[name] = metric_current(metrics, name)
    metric_grid((name, shown(value, ".3f")) for name, value in holder_values.items())
    if latest:
        state = sth_state({name: metric_current(metrics, name) for name in ("btc_price_usd", "sth_mvrv", "sth_sopr", "sth_realized_price")})
        st.write("**STH state:**", state or "N/A")
        missing = [label for label,key in (("LTH-MVRV","lth_mvrv"),("STH-MVRV","sth_mvrv"),("MVRV Z","mvrv_zscore"),("LTH Distribution","lth_distribution")) if latest.get(key) is None]
        text = f"現在のフェーズは{safe_phase(latest['cycle_phase'], latest['confidence'], latest['date'])}。"
        if (datetime.now(timezone.utc).date() - latest["date"]).days <= 3 and latest["lth_distribution"] is not None: text += f"長期保有者の分配スコアは{latest['lth_distribution']:.1f}。"
        if metric_current(metrics, "sth_mvrv") is not None and latest["sth_mvrv"] is not None: text += "短期保有者は平均的に含み益。" if latest["sth_mvrv"] >= 1 else "短期保有者は平均的に含み損。"
        if missing: text += " 欠損: " + "、".join(missing) + "。欠損値は推定していません。"
        st.info("**Daily Interpretation:** " + text)
    st.caption("LTH = Long-Term Holder / STH = Short-Term Holder。Glassnode利用時は公式の155日分類を変更しません。")
for tab, asset in ((tabs[2], "GOLD"), (tabs[3], "SILVER")):
    with tab:
        st.header(f"{asset.title()} Institutional Flow")
        rows=[x for x in metal_snapshots if x["asset"]==asset]; m=rows[-1] if rows else None
        if not m: st.info("取得済みデータなし / Unavailable")
        else:
            labels=(("Price",m["price"]),("Institutional Demand (参考値)" if m["confidence"]<50 else "Institutional Demand",m["demand_score"]),("Top Risk (参考値)" if m["confidence"]<50 else "Top Risk",m["top_risk_score"]),("Dip Quality",m["dip_quality_score"]),("Phase",safe_phase(m["phase"],m["confidence"],m["date"],m["asset"])),("Confidence",f'{shown(m["confidence"])}% · {confidence_label(m["confidence"])}'))
            for col,(label,value) in zip(st.columns(6),labels): col.metric(label, shown(value) if isinstance(value,(int,float)) else value)
            if m["price"] is None: st.warning("Dip Quality: N/A — Price unavailable。CFTCが取得済みでも価格不足のため正式判定を保留します。")
        price_rows = pd.DataFrame(selected_metric_rows(metrics, f"{asset.lower()}_price_usd"))
        if not price_rows.empty:
            ps = metric_series(metrics, f"{asset.lower()}_price_usd")
            stats = {"7D %": ps.pct_change(7, fill_method=None).iloc[-1]*100, "30D %": ps.pct_change(30, fill_method=None).iloc[-1]*100,
                     "90D %": ps.pct_change(90, fill_method=None).iloc[-1]*100, "50DMA": ps.rolling(50).mean().iloc[-1],
                     "200DMA": ps.rolling(200).mean().iloc[-1], "Drawdown %": (ps.iloc[-1]/ps.cummax().iloc[-1]-1)*100,
                     "履歴内最高値から %": (ps.iloc[-1]/ps.max()-1)*100}
            if current_metric_row(metrics, f"{asset.lower()}_price_usd") is None:
                stats = dict.fromkeys(stats)
            stats = {label.replace("7D", "7取引日").replace("30D", "30取引日").replace("90D", "90取引日"): value for label, value in stats.items()}
            for col,(label,value) in zip(st.columns(7),stats.items()): col.metric(label, shown(value))
            latest_price = price_rows.iloc[-1]
            st.markdown(f"**Price Source:** {latest_price.source}　 **Price Type:** {latest_price.price_type or 'N/A'}　 **観測日:** {latest_price.date}")
            st.caption("ETF_PROXYは1口あたりのUSD価格、現物・先物は1トロイオンスあたりのUSD価格です。種類の異なる価格系列は接続しません。")
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
        asset_etfs = latest_fund_rows(asset, fresh_only=True)
        if m:
            demand_state = "取得不可" if m["demand_score"] is None else "Strong Buying" if m["demand_score"] >= 75 else "Moderate Buying" if m["demand_score"] >= 55 else "Neutral / Weak"
            risk_state = "取得不可" if m["top_risk_score"] is None else "Elevated" if m["top_risk_score"] >= 60 else "Normal"
            if safe_phase(m["phase"], m["confidence"], m["date"], m["asset"]) == "判定保留 / PARTIAL":
                demand_state = risk_state = "判定保留 / 参考値"
            st.markdown(f"**Demand State:** {demand_state}　 **Positioning Risk:** {risk_state}")
            missing = []
            if m["price"] is None: missing.append("Price")
            if asset_etfs.empty: missing.append("ETF holdings")
            if not asset_cot: missing.extend(["CFTC Managed Money", "Open Interest"])
            st.caption("不足データ / Missing: " + (", ".join(missing) if missing else "なし。スコアは実測入力のみ。"))
        expected_funds = {"GOLD": {"GLD", "IAU"}, "SILVER": {"SLV"}}[asset]
        available_funds = {fund for fund in expected_funds if quality["sources"][fund]["status"] == "OK"}
        etf_status = "OK" if available_funds == expected_funds else "PARTIAL" if available_funds else "N/A"
        st.markdown(f"**ETF Data:** {', '.join(sorted(available_funds)) or 'N/A'}　 **ETF Status:** {etf_status}")
        st.subheader("ETF (official sponsor data)")
        if asset_etfs.empty: st.info("Holdings / shares outstanding / flow: N/A")
        else: st.dataframe(asset_etfs.groupby("fund").tail(1)[["fund","effective_date","shares_outstanding","physical_holdings","holdings_unit","net_assets","flow","flow_status","status","fetched_at","source"]], hide_index=True, width="stretch")
with tabs[4]:
    st.header("BTC / Gold / Silver Compare")
    comparison = []
    if latest:
        comparison.append({"asset": "BTC", "price": latest["btc_price"], "Cycle / Demand": latest["cycle_score"],
                           "Top Risk": latest["top_risk_score"], "Dip Quality": None,
                           "phase": safe_phase(latest["cycle_phase"], latest["confidence"], latest["date"]),
                           "confidence": latest["confidence"], "date": latest["date"]})
    for m in {x["asset"]: x for x in metal_snapshots}.values():
        comparison.append({"asset": m["asset"], "price": m["price"], "Cycle / Demand": m["demand_score"],
                           "Top Risk": m["top_risk_score"], "Dip Quality": m["dip_quality_score"],
                           "phase": safe_phase(m["phase"], m["confidence"], m["date"], m["asset"]),
                           "confidence": m["confidence"], "date": m["date"]})
    if comparison:
        st.dataframe(pd.DataFrame(comparison), hide_index=True, width="stretch")
        st.caption("BTCはCycle、金・銀はDemandを表示。指標の定義が異なるため数値の大小だけで比較しないでください。価格単位・代理値の種類は各資産タブに表示します。")
    else:
        st.info("比較する保存済みデータがありません。")
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
    st.write("モード:", "GLASSNODE MODE" if get_settings().glassnode_api_key else "FREE MODE")
    if not get_settings().glassnode_api_key: st.info("無料モードでは、公開価格・Global MVRV・金銀ETF・CFTCを利用します。LTH/STH高度指標は対応するGlassnode契約とAPIキーが必要です。欠損があるBTCの正式判定は保留されます。")
    if not metric_df.empty: st.dataframe(metric_df[["date", "metric_name", "value", "source", "status", "fetched_at"]].sort_values("fetched_at", ascending=False), hide_index=True, width="stretch")
    st.subheader("Gold / Silver sources")
    st.write("CFTC Public Reporting (official):", "OK" if all(quality["sources"][f"{a}_cot"]["status"] == "OK" for a in ("gold", "silver")) else "PARTIAL / STALE")
    st.write("ETF official sponsor feeds:", "OK" if all(quality["sources"][fund]["status"] == "OK" for fund in ("GLD", "IAU", "SLV")) else "PARTIAL / UNAVAILABLE")
    if etfs:
        st.dataframe(pd.DataFrame(etfs)[["fund","asset","source","status","effective_date","fetched_at","error"]].sort_values("fetched_at", ascending=False), hide_index=True, width="stretch")
    st.subheader("Data Status / Freshness SLA")
    statuses = [{"データ": name, **state} for name, state in quality["sources"].items()]
    st.dataframe(pd.DataFrame(statuses), hide_index=True, width="stretch")
    for message in quality["essential_failures"] + quality["warnings"]:
        st.caption(message)
    st.caption(f"表示時刻: {datetime.now(timezone.utc).isoformat()} · UI cache TTL: {get_settings().cache_ttl_seconds}秒")
