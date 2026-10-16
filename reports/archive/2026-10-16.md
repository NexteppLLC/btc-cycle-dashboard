# BTC / Gold / Silver 日次レポート

保存済み集計日（UTC）：2026-10-16
判定確認日（UTC）：2026-10-16
レポート生成（JST）：2026-10-16 20:31

| 資産 | 最新価格 | 観測時刻 | 24h | 前回レポート比 | 相場局面 | Confidence |
|---|---:|---|---:|---:|---|---:|
| BTC | $82,668.20 USD | 2026-10-16 20:30 JST | 0.65% | 2.01% | PARTIAL | 25.0% |
| GOLD | $4,198.40 USD / troy oz (FUTURES_PROXY) | 2026-10-16 20:20 JST | 0.68% | 0.48% | BEAR | 100.0% |
| SILVER | $58.02 USD / troy oz (FUTURES_PROXY) | 2026-10-16 20:20 JST | 1.52% | 2.02% | DISTRIBUTION | 100.0% |


## Bitcoin
- Latest：82,668.20 USD
- Observed：2026-10-16 20:30 JST
- Source：Kraken Public Ticker
- Symbol / Type：XBT/USD / SPOT
- Freshness：FRESH（age 0.0 min）
- Market State：OPEN
- Last UTC Daily Close：82,133.70 USD

- BTC確定日足：82,134 USD
- フェーズ：判定保留 / PARTIAL
- Cycle Score（参考値）：44.89 / 100
- Top Risk（参考値）：4.03 / 100
- Confidence（データ充足度）：25.0%
- Global MVRV：1.52
- MVRV Z-Score：取得不可
- LTH-MVRV：取得不可
- STH-MVRV：取得不可
- LTH Distribution：取得不可 / 100
- ETF 最新観測フロー：取得不可
- ETF 最新観測日を含む7暦日合計：取得不可

## BTC 5-Signal Monitor
- STH-MVRV：取得不可 · 観測日 2026-10-16 · Status UNAVAILABLE_NO_API_KEY
- STH-SOPR：取得不可 · 観測日 2026-10-16 · Status UNAVAILABLE_NO_API_KEY
- LTH-MVRV：取得不可 · 観測日 2026-10-16 · Status UNAVAILABLE_NO_API_KEY
- LTH Distribution：取得不可 · 観測日 取得不可 · Status UNAVAILABLE
- Sell-Side Risk 15日SMA：取得不可 · 観測日 2026-10-16 · Status UNAVAILABLE_NO_API_KEY · 理由 Sell-Side input request unavailable
- Short-Term Health：PARTIAL
- Cycle Heat：PARTIAL
- Distribution Pressure：PARTIAL
- BTC 5-Signal State：PARTIAL
- 判定理由：欠損: sth_mvrv, sth_sopr, lth_mvrv, distribution, sell_side_risk / Distribution入力充足率 0% / Core 5の観測日が一致しません

Core 5は既存スコアと独立した観測レイヤーです。オンチェーン移動は取引所で確認された売却量を意味しません。

## 本日の解釈
主要指標が不足しているため、BTCのサイクル判定を保留します。表示スコアは利用可能なデータのみの参考値です。低いTop Riskを安全の根拠として扱いません。
取得不可の指標は推測・ゼロ補完しません。LTH/STHなどの契約制限は、無料モードでは取得不可として明示します。

## Gold
- Latest：4,198.40 USD / troy oz
- Observed：2026-10-16 20:20 JST
- Source：Yahoo Finance GC=F intraday (query1)
- Symbol / Type：GC=F / FUTURES_PROXY
- Freshness：FRESH（age 10.1 min）
- Market State：UNKNOWN
- Previous completed daily close：4,170.10 USD

- 保存済み集計日（UTC）：2026-10-16
- 価格：4,170.10 USD（現物・先物・ETF代理値の区別はソース参照）
- フェーズ：BEAR / 弱気相場
- Institutional Demand：37.50 / 100
- Top Risk：51.30 / 100
- Dip Quality：47.00 / 100
- Confidence：100.0%

## Silver
- Latest：58.02 USD / troy oz
- Observed：2026-10-16 20:20 JST
- Source：Yahoo Finance SI=F intraday (query1)
- Symbol / Type：SI=F / FUTURES_PROXY
- Freshness：FRESH（age 10.3 min）
- Market State：UNKNOWN
- Previous completed daily close：56.84 USD

- 保存済み集計日（UTC）：2026-10-16
- 価格：56.84 USD（現物・先物・ETF代理値の区別はソース参照）
- フェーズ：DISTRIBUTION / 分配局面
- Institutional Demand：41.20 / 100
- Top Risk：37.50 / 100
- Dip Quality：49.50 / 100
- Confidence：100.0%

## データの状態
更新結果：一部取得不可

- btc_price_latest：OK · Kraken Public Ticker / SPOT / 2026-10-16
- btc_price_usd：OK · Kraken Public Ticker / SPOT / 2026-10-16
- gold_price_latest：OK · Yahoo Finance GC=F intraday (query1) / FUTURES_PROXY / 2026-10-16
- gold_price_usd：OK · Yahoo Finance GC=F intraday (query1) / FUTURES_PROXY / 2026-10-16
- silver_price_latest：OK · Yahoo Finance SI=F intraday (query1) / FUTURES_PROXY / 2026-10-16
- silver_price_usd：OK · Yahoo Finance SI=F intraday (query1) / FUTURES_PROXY / 2026-10-16
- global_mvrv：OK
- lth_mvrv：UNAVAILABLE_NO_API_KEY · Glassnode API v1 availability
- sth_mvrv：UNAVAILABLE_NO_API_KEY · Glassnode API v1 availability
- mvrv_zscore：UNAVAILABLE_NO_API_KEY · Glassnode API v1 availability
- lth_realized_price：UNAVAILABLE_NO_API_KEY · CALCULATED_FROM_GLASSNODE_PRICE_LTH_MVRV availability
- sth_realized_price：UNAVAILABLE_NO_API_KEY · Glassnode API v1 availability
- lth_sopr：UNAVAILABLE_NO_API_KEY · Glassnode API v1 availability
- sth_sopr：UNAVAILABLE_NO_API_KEY · Glassnode API v1 availability
- lth_supply：UNAVAILABLE_NO_API_KEY · Glassnode API v1 availability
- sth_supply：UNAVAILABLE_NO_API_KEY · Glassnode API v1 availability
- lth_spent_volume：UNAVAILABLE_NO_API_KEY · Glassnode API v1 availability
- lth_realized_profit：UNAVAILABLE_NO_API_KEY · Glassnode API v1 availability
- cdd：UNAVAILABLE_NO_API_KEY · Glassnode API v1 availability
- etf_flow_usd：PENDING · Operator-configured ETF CSV
- sell_side_risk_15d：UNAVAILABLE_NO_API_KEY · Glassnode API v1 Sell-Side Risk availability
- gold_cot：OK
- silver_cot：OK
- GLD：OK · 2026-10-15
- IAU：OK · 2026-10-15
- SLV：OK · 2026-10-15

市場指標はそれぞれの観測日が基準です。CFTCは週次、ETF保有量はスポンサー公表日を使用します。

> 分析支援用の指標です。スコアは将来の値動きや利益を保証しません。
