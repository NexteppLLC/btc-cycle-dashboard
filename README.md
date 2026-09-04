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
| 本当に取得したデータ | BTC/USD、realized cap、market cap、active addresses、tx count | [Coin Metrics Community API v4](https://docs.coinmetrics.io/api/v4/) の `timeseries/asset-metrics` |
| fallback 実測値 | BTC/USD | [CoinGecko Demo API](https://docs.coingecko.com/reference/coins-id-market-chart-range)（Coin Metrics価格取得失敗時のみ） |
| 任意の実測値 | Glassnode 指標 | [Glassnode API](https://docs.glassnode.com/basic-api/api) v1。キーと契約権限がある場合のみ |
| 任意の実測値 | ETF flow | 管理者が利用条件を確認して指定する構造化 CSV (`date,flow_usd[,fund]`) |
| 計算したデータ | MVRV、移動平均、騰落率、volatility、RSI、drawdown、各スコア | 上記の保存済み実測値から計算 |
| 取得不可 | Glassnode未契約指標、未設定/未公表ETF、障害中のAPI | `UNAVAILABLE_NO_API_KEY`, `UNAVAILABLE`, `PENDING`, `ERROR`。数値は `None` |

ETF は利用規約や HTML 変更リスクを避けるため、Farside 等を無断スクレイピングしません。利用者が利用許諾を確認した安定 CSV を `ETF_FLOW_CSV_URL` に指定します。CSV がなければ Pending のままで、架空値は表示しません。

### 公式仕様の確認について

実装は Coin Metrics Community API v4、Glassnode `/v1/metrics`、CoinGecko market chart range の公式ドキュメント上のインターフェースに分離しています。外部 API は変更され得るため、本番導入前と更新時に上記リンクのパラメータ、提供ティア、利用規約を再確認してください。Glassnode の利用可能メトリクスは契約で異なり、401/403/404 はアプリ停止ではなく `UNAVAILABLE` になります。LTH/STH の 155 日分類をアプリ独自の日数で再定義しません。

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

初期重みは LTH-MVRV 25%、STH-MVRV 20%、LTH Distribution 20%、ETF Flow 15%、MVRV Z 10%、BTC 30日トレンド 10%。絶対範囲を0–100へ正規化し、欠損成分を0とは扱わず**利用可能成分だけで再ウェイト**します。寄与点と理由は `scoring_detail` に保存します。coverage 低下は Confidence に反映されます。

### LTH Distribution

LTH spent volume z-score、LTH SOPR、realized profit z-score、supply change、CDD z-scoreを候補にします。利用可能成分だけを再ウェイトし、充足率も返します。0–20 蓄積、20–40 通常、40–60 軽度利益確定、60–75 分配開始、75–90 強い分配、90–100 極端な分配の目安です。

### Top Risk

LTH-MVRV、MVRV Z、LTH SOPR、Distribution、STH-MVRV、ETF divergence、200DMA乖離を独立に合成します。`Low / Normal / Caution / High / Very High / Extreme` の区分です。Cycle Scoreだけでフェーズを決めず、Top Risk、トレンド、分配、STH profitabilityも条件にします。

### Confidence

利用可能なスコア重みを基礎とし、Glassnode未接続、ETF Pending、古いデータ、履歴不足、矛盾を減点します。Confidence が低い判定は断定材料にしないでください。

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
