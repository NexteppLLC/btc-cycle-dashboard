# Bitcoin On-Chain Cycle Dashboard

Bitcoin の価格だけで天井・底を決めず、**価格トレンド、オンチェーン評価、長期/短期保有者、利益確定、米国現物 ETF 需要**を組み合わせて相場フェーズを毎日説明する個人向け Streamlit ダッシュボードです。日本語 UI、SQLite、設定可能なスコア、欠損を前提とした設計を採用しています。

> **重要:** 分析支援ツールであり、金融・投資助言ではありません。取得できない値は推測・0補完・前日コピーをせず「取得不可」「Pending」と表示します。

## 30秒で分かること

- `BEAR / ACCUMULATION / EARLY_BULL / MID_BULL / LATE_BULL / TOP_RISK / DISTRIBUTION` のどこか
- Cycle Score（0=弱気深部、50=上昇中期、100=極端な過熱）
- Top Risk（方向感ではなくサイクル天井への近さ）
- LTH Distribution、STH の収益性、ETF の新規需要
- スコアの構成要因、データソース、取得時刻、欠損を反映した Confidence

## スクリーンショット

![Dashboard screenshot placeholder](docs/dashboard.png)

`docs/dashboard.png` はローカル起動後の画面例を置く場所です（実データやAPIキーを含む画像は公開前に確認してください）。

## かんたんインストール（Python 3.12+）

```bash
git clone <repository-url>
cd btc-cycle-dashboard
python -m venv .venv
source .venv/bin/activate              # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
python scripts/init_db.py
streamlit run app.py
```

ブラウザが自動で開かない場合は `http://localhost:8501` を開きます。初回 DB は自動作成されます。データ取得は別プロセスなので、最初に `python scripts/update_data.py` を実行してください。

## データの区別とソース

| 区分 | 内容 | ソース/扱い |
|---|---|---|
| 本当に取得したデータ | BTC/USD daily OHLC close | [Kraken public OHLC](https://docs.kraken.com/api/docs/rest-api/get-ohlc-data/) の `XBTUSD`, interval 1440（primary） |
| fallback 実測値 | BTC/USD daily close | [Coinbase Exchange public candles](https://docs.cdp.coinbase.com/exchange/reference/exchangerestapi_getproductcandles) の `BTC-USD`（300本単位で取得） |
| spot/proxy 実測値 | Gold/Silver daily close | Yahoo chart の `XAUUSD=X` / `XAGUSD=X` (SPOT)、`GC=F` / `SI=F` (FUTURES_PROXY)、`GLD` / `SLV` (ETF_PROXY) の順。source と price_type をDB/UIへ保存 |
| 公式ETF実測値 | GLD / IAU / SLV holdings, shares, NAV（公表ファイルに存在する項目のみ） | [SPDR Gold Shares](https://www.spdrgoldshares.com/usa/historical-data/) / [iShares IAU](https://www.ishares.com/us/products/239561/ishares-gold-trust-fund) / [iShares SLV](https://www.ishares.com/us/products/239855/ishares-silver-trust-fund) のスポンサーCSV |
| 任意の実測値 | Glassnode 指標 | [Glassnode API](https://docs.glassnode.com/basic-api/api) v1。キーと契約権限がある場合のみ |
| 任意の実測値 | ETF flow | 管理者が利用条件を確認して指定する構造化 CSV (`date,flow_usd[,fund]`) |
| 計算したデータ | MVRV、移動平均、騰落率、volatility、RSI、drawdown、各スコア | 上記の保存済み実測値から計算 |
| 取得不可 | Glassnode未契約指標、未設定/未公表ETF、障害中のAPI | `UNAVAILABLE_NO_API_KEY`, `UNAVAILABLE`, `PENDING`, `ERROR`。数値は `None` |

### オンチェーンAPI調査結果（2026-09-04確認）

分類は **A=キー不要で無料、B=キー必要・無料枠あり、C=有料API必須、D=信頼できる公開APIから取得不可** です。公開仕様として確認できても、本リポジトリの実行環境で外部ネットワークが拒否された項目は実データ検証済みとはしていません。Glassnodeは契約tierにより個別メトリクスの権限が異なります。

| 指標 | 分類 | Free mode / 採用ソース | Glassnode mode |
|---|---:|---|---|
| Global MVRV | A | Coin Metrics CommunityのMarket Cap÷Realized Cap。`CALCULATED_FROM_MARKET_CAP_REALIZED_CAP` | C: market/mvrv |
| MVRV Z-Score | C | N/A（別指標から近似しない） | C |
| LTH-MVRV / STH-MVRV | C | N/A | C |
| LTH / STH Realized Price | C | N/A | C |
| Global Realized Price | A | Coin Metrics CommunityのRealized Cap÷Current Supply | Cでも取得可 |
| LTH-SOPR / STH-SOPR | C | N/A | C |
| aSOPR | C | N/A | C |
| LTH / STH Spent Volume | C | N/A | 契約・endpoint権限を確認後のみ（現状N/A） |
| LTH / STH Supply | C | N/A | C |
| LTH Realized Profit / Loss | C | N/A | 契約・endpoint権限を確認後のみ（現状N/A） |
| CDD / Dormancy | C | Communityで提供を確認できないためN/A | C |
| Exchange inflow関連 | C | N/A | C（取引所ラベル由来） |
| Active Addresses / Transaction Count | A | Coin Metrics Community | 同左 |
| Realized Cap / Market Cap | A | Coin Metrics Community | 同左 |

調査対象のうち、Blockchain.comは価格・チェーン統計の公開Charts API、Mempool.spaceはmempool/ブロック/手数料の公開APIとして有用ですが、上記LTH/STH cohort指標の代替にはしません。CryptoQuant、Bitbo、CoinGlassにも表示ページや提供商品はありますが、無認証の安定した公式APIを本実装の根拠として確認できなかったため採用していません（Dではなく、該当高度指標はC扱い）。画面値をHTMLから無断取得する実装も行いません。

ETF は利用規約や HTML 変更リスクを避けるため、Farside 等を無断スクレイピングしません。利用者が利用許諾を確認した安定 CSV を `ETF_FLOW_CSV_URL` に指定します。CSV がなければ Pending のままで、架空値は表示しません。

### 公式仕様の確認について

価格実装は API キー不要の Kraken public OHLC を primary、Coinbase Exchange public candles を fallback とします。Krakenの720本制限でも200DMAに必要な履歴を満たし、fallbackは公式の300本上限に従い分割します。外部 API は変更され得るため、本番導入前と更新時に上記リンクのパラメータ、利用規約を再確認してください。Glassnode の利用可能メトリクスは契約で異なり、401/403/404 はアプリ停止ではなく `UNAVAILABLE` になります。

## FREE MODE

Glassnode キーなしで起動できます。利用可能なのは BTC価格、Coin Metrics Community 指標、テクニカル、設定済みETF CSV、保存済み履歴です。Glassnode 専用カードには「Glassnode API未接続」と表示し、別データから Glassnode 値を推定しません。よって Cycle/Top Risk が未判定になるか、低い Confidence で部分計算される場合があります。

## Glassnode と Secrets

`.env`（Git除外済み）へ次のように設定します。キーをコード、ログ、Issue、画像へ貼らないでください。

```dotenv
GLASSNODE_API_KEY=your-key
ETF_FLOW_CSV_URL=https://approved.example/flows.csv
```

GitHub では **Settings → Secrets and variables → Actions** に `GLASSNODE_API_KEY` と必要なら `ETF_FLOW_CSV_URL` を登録します。`.env.example` は空欄しか含みません。

接続後、契約プランが許す MVRV、MVRV Z-Score、Realized Price、LTH/STH MVRV、LTH/STH SOPR、aSOPR、LTH/STH supply、CDD を取得します。アクセス不可はエラー値へ置き換えず `UNAVAILABLE` です。spent volume、realized profit/loss、LTH/STH realized price はエンドポイント/契約メタデータを利用者が確認した上で adapter のマッピングを追加する余地があります。

## スコアの考え方

閾値・重みは [`config/thresholds.yaml`](config/thresholds.yaml) で変更できます。

### Cycle Score

初期重みは LTH-MVRV 25%、STH-MVRV 20%、LTH Distribution 20%、ETF Flow 10%、MVRV Z 10%、BTC 30日トレンド 10%、STH Stress/Recovery 5%。絶対範囲を0–100へ正規化し、欠損成分を0とは扱わず**利用可能成分だけで再ウェイト**します。寄与点と理由は `scoring_detail` に保存します。coverage 低下は Confidence に反映されます。

### LTH Distribution

LTH spent volume z-score、LTH SOPR、realized profit z-score、supply change、CDD z-scoreを候補にします。利用可能成分だけを再ウェイトし、充足率も返します。0–20 蓄積、20–40 通常、40–60 軽度利益確定、60–75 分配開始、75–90 強い分配、90–100 極端な分配の目安です。

### Top Risk

LTH-MVRV、MVRV Z、LTH SOPR、Distribution、STH-MVRV、ETF divergence、200DMA乖離を独立に合成します。`Low / Normal / Caution / High / Very High / Extreme` の区分です。Cycle Scoreだけでフェーズを決めず、Top Risk、トレンド、分配、STH profitabilityも条件にします。

### Confidence

入力充足率は Price 10%、Global MVRV 10%、MVRV Z 10%、LTH-MVRV 15%、STH-MVRV 15%、LTH Distribution 20%、SOPR 10%、ETF 5%、Trend 5%です。50%未満、またはPrice・Trend・major on-chain 2指標という最低条件未達ならPhaseは`PARTIAL`です。

## 更新・履歴・レポート

```bash
python scripts/update_data.py
python scripts/backfill.py --start 2020-01-01 --end 2026-09-01
```

更新は collector ごとに障害分離され、有限回の指数バックオフを行います。HTTP 429/5xx/timeout/JSON不正/スキーマ不一致はログへ秘密情報なしで記録します。日次一意制約と upsert により再実行できます。レポートは `reports/latest.md` と `reports/archive/YYYY-MM-DD.md` に生成されます。

## 画面

- **Overview:** 現在フェーズ、重要KPI、Confidence、今日の変化
- **MVRV / Holders:** 実測値・source・取得時刻、未接続状態
- **ETF:** 1D/ローリングフロー、Pending状態
- **Technical:** BTC、50/100/200DMA、50/200WMA相当、RSI、drawdown（履歴不足はNone）
- **History:** Cycle/Top Risk と Phase 変化点
- **System:** 全データの source/status/fetched_at と動作モード

鮮度目安は Fresh（24h以内）、Delayed（24–48h）、Stale（48h超）。ソース固有の公開頻度を優先して解釈します。

## GitHub Actions

- `tests.yml`: push / pull request で Python 3.12 と `pytest -q`。
- `daily_update.yml`: 毎日 `22:45 UTC`（日本時間 07:45）と手動 `workflow_dispatch`。更新・レポートを commit します。書込み権限や branch protection により push できない場合は、PR方式または artifact 保存へ変更してください。

## テスト

```bash
pytest -q
```

正常レスポンス、HTTP障害、欠損、キーなし、SQLite保存、重複防止、Cycle、Top Risk、phase、confidence を外部通信なしの mock で検証します。

## Troubleshooting

- **画面が空:** `python scripts/update_data.py` を実行し、System タブの status を確認。
- **Glassnodeが取得不可:** `.env` の名称、契約プラン、公式メトリクス権限を確認。キー自体はログに出ません。
- **ETFがPending:** `ETF_FLOW_CSV_URL` 未設定、CSV列不足、または当日未公表です。`date,flow_usd` 列を確認。
- **429:** retry後も制限中です。時間を空け、backfill の `--chunk-days` と `--sleep` を調整。
- **DBを作り直す:** アプリ停止後 `data/btc_cycle.db` を退避し `python scripts/init_db.py`。履歴は失われるため先にバックアップ。

## 現在の制約と次の改善

APIキーなしでは有料オンチェーン指標を実データ検証できません。ETFの普遍的な公式無料APIも前提にせず、許諾済みCSV方式です。次は Glassnode metadata に基づく動的 capability discovery、全履歴 percentile/rolling z-scoreのスナップショット保存、ファンド別ETF比較、取引日カレンダー対応、freshnessの指標別SLA、通知adapter（Email/Slack/Discord/Telegram）を追加するのが適切です。
# Gold / Silver Institutional Flow (Phase 2)

The dashboard compares BTC with COMEX Gold and Silver for medium-term swing analysis. It adds
Institutional Demand, Top Risk, Buy-the-Dip Quality, divergence, phase and confidence. This is an
analysis-support tool, **not financial advice**; unavailable observations remain `N/A` and are never
replaced by zero or invented values.

## CFTC positioning and freshness

The collector uses the CFTC's official **Disaggregated Futures Only** public dataset (`72hh-3qpy`):
Gold contract market code `088691` and Silver `084691`. Producer/Merchant, Swap Dealer, Managed
Money, Other Reportable and Nonreportable long/short/spreading positions plus open interest are
stored with source, effective report date, fetch time and status. COT observations describe Tuesday
positions and are normally released Friday; they remain weekly and are not forward-filled as daily
facts. Price/COT timestamp differences and age appear in the UI.

Managed Money analytics include net (`long - short`), ratios to OI, 1/4/13-week changes, z-score and
52-week/3-year/full-history percentiles. Insufficient history produces `N/A`. Price/OI combinations
distinguish participation, short covering, new shorts and liquidation.

## Scores

Weights are auditable in `config/thresholds.yaml`. Institutional Demand is 25% MM trend, 15% MM
percentile, 20% ETF, 15% OI confirmation, 10% commercials, 10% divergence and 5% trend. Top Risk
combines MM net/long extremes, long-MA distance, ETF exhaustion, bearish divergence, OI,
commercials and momentum. Dip Quality is emitted only during a drawdown and combines drawdown
shape, position reset, ETF stability, OI reset, commercial covering, long trend and reaccumulation;
the BAD_DIP conjunction caps the result. Silver has separate, more volatility-tolerant thresholds.

## ETF data and limitations

GLD, IAU and SLV are represented by the additive `etf_holdings` schema. The collector reads only
official sponsor CSV downloads and populates fields that the published file identifies. Missing
fields and flow remain `N/A`; holdings/share changes are not relabelled as measured cash flow. Any
future inferred flow must carry `ESTIMATED` status.
World Gold Council regional data likewise remains unavailable rather than guessed.

Backfill ten years (or specify dates):

```bash
python scripts/backfill.py --asset gold
python scripts/backfill.py --asset silver
```

The daily GitHub Actions job updates all prices and checks CFTC for a new weekly observation. Long
history is persisted in SQLite and Streamlit reads cached DB results rather than fetching on render.
