# BTC / Gold / Silver Cycle Dashboard

BTCの価格・オンチェーン指標・保有者行動と、金・銀の価格・CFTC建玉・公式ETF保有量を確認する日本語Streamlitアプリです。SQLiteに履歴を保存し、日次レポートを生成します。

**取得不可の値を推測・ゼロ補完しません。** 古いデータや不十分な入力は現在の判定から除外し、必要条件を満たさない場合は **判定保留 / PARTIAL** と表示します。スコアは分析支援用で、将来の価格や利益を保証しません。

## 起動する

Python 3.12、Streamlit 1.63以降を使用します。

```bash
git clone https://github.com/NexteppLLC/btc-cycle-dashboard.git
cd btc-cycle-dashboard
python -m venv .venv
```

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

macOS / Linux:

```bash
source .venv/bin/activate
```

```bash
python -m pip install -r requirements.txt
python scripts/init_db.py
python -m streamlit run app.py
```

ブラウザで `http://localhost:8501` を開きます。保存データがない場合は、サイドバーの **データを取得・更新** を押します。**最新の保存データを表示** は表示キャッシュのみを更新します。**日次レポートを保存** からMarkdownをダウンロードできます。

コマンドからの更新:

```bash
python scripts/update_data.py --diagnostics-json data/update-diagnostics.json
```

`data/update-diagnostics.json` は任意の診断出力です。主要価格が欠けた更新は終了コード1となり、GitHub ActionsはそのDB・レポートを公開しません。キー未設定などの任意データ不足は、数値を補わず警告として報告します。

## 無料モードと取得できる指標

| 指標 | 取得元と扱い |
|---|---|
| BTC価格 | Krakenの日足終値。必要な履歴が足りない場合などはCoinbaseのページ分割取得を利用。未確定の当日足を確定終値として使わない |
| Global MVRV | Coin Metrics Communityの公開指標 `CapMVRVCur` を直接取得 |
| Market Cap / Supply / Active Addresses / Transactions | Coin Metrics Communityの利用可能な公開指標を取得。拒否された1項目で他の項目まで失敗させない |
| Global Realized Cap / Realized Price | 同一時点の実測Market Cap ÷ MVRV、さらにSupplyで除算。式と由来を区別し、入力が欠けたら取得不可 |
| LTH/STH MVRV・SOPR・Supply等 | 対応するGlassnode契約とAPIキーが必要。無料モードで別指標からコホート値を推定しない |
| 金・銀価格 | Yahooの日足。現物→先物→ETF代理値の優先順。`source` / `price_type` / 観測日を表示 |
| GLD | [SPDR公式の履歴ページ](https://www.spdrgoldshares.com/usa/historical-data/)から案内されるネイティブExcel履歴 |
| IAU / SLV | [IAU](https://www.ishares.com/us/products/239561/ishares-gold-trust-fund) / [SLV](https://www.ishares.com/us/products/239855/ishares-silver-trust-fund)の公式BlackRockダウンロード、または観測日が明示されたスポンサーの保有量表示 |
| 金・銀CFTC建玉 | [CFTC Public Reporting](https://publicreporting.cftc.gov/)のDisaggregated Futures Only。火曜時点、通常金曜公表の週次データ |
| BTC ETFドルフロー | 利用者が指定する構造化CSV。未設定時は取得不可 |

Coin Metricsの`CapRealUSD`はCommunity APIで拒否される場合があるため、無料で利用可能な`CapMVRVCur`を使います。取得権限は提供者側で変更され得ます。拒否・欠損・HTTP障害はそれぞれ明示します。

**無料モードでGlobal MVRVが表示されても、BTCの正式なフェーズ判定は保留される場合があります。** 初期設定ではLTH/STH等の主要指標2つとConfidence 50%以上が必要です。これは有料指標の欠損を無理に埋めないための仕様です。

金・銀のETF保有量増減は、ドル建て資金フローそのものではありません。公表された物理保有量または発行済口数の同じ項目を、異なる観測日で比較します。NAVや純資産額の値上がりを資金流入とみなしません。

## 設定

必要な場合だけ、Gitに保存されない `.env` に設定します。

```dotenv
GLASSNODE_API_KEY=
ETF_FLOW_CSV_URL=
```

| 設定 | 初期値 / 用途 |
|---|---|
| `DATABASE_URL` | リポジトリ内の `data/btc_cycle.db`。別の保存先も指定可 |
| `GLASSNODE_API_KEY` | 任意。指標ごとの契約権限に従う |
| `ETF_FLOW_CSV_URL` | 任意。`date,flow_usd[,fund]` のCSV |
| `HTTP_TIMEOUT_SECONDS` | 20秒 |
| `CACHE_TTL_SECONDS` | 900秒。サイドバーから表示キャッシュの更新可 |
| `GOLD_PRICE_PRIORITY` | `XAUUSD=X,GC=F,GLD` |
| `SILVER_PRICE_PRIORITY` | `XAGUSD=X,SI=F,SLV` |

BTC ETF CSVは1日1行の合計値、または一意な`TOTAL`行を推奨します。ファンド別の行を使う場合は日付ごとに同じ構成ファンドを揃えます。欠けたファンドや重複行を黙って除外した部分合計は保存しません。

APIキーや、認証情報を含むCSV URLをコード・ログ・Issueへ貼らないでください。GitHub Actionsでは **Settings → Secrets and variables → Actions** のSecretsに設定します。未設定でも無料データの更新は動作します。

## 画面と判定

- **Overview**: 保存済み集計日、BTCフェーズ・スコア・充足度、3資産の概要。
- **Bitcoin**: 価格・移動平均・MVRV・Realized Priceチャート、LTH/STHの全指標と取得元。
- **Gold / Silver**: 価格の種類と単位、需要・天井リスク・押し目評価、CFTCとETF保有量。
- **Compare**: BTC・金・銀の比較。BTC Cycleと金銀Demandは別の指標。
- **History**: スコアとフェーズの保存履歴。
- **System**: 取得元・観測日・取得日時・欠損理由・データ鮮度。

Cycle Score、Top Risk、Confidenceの閾値・重みは [`config/thresholds.yaml`](config/thresholds.yaml) にあります。欠損成分は利用可能成分へ再配分しますが、Confidenceと最低条件によって正式判定を制限します。低い参考Top Riskは「安全」を意味しません。

金・銀では需要評価と天井リスク・押し目評価を分けます。必要な実測値がない構成要素は取得不可のままです。価格と週次CFTCの比較は同じ期間で行い、建玉の週が飛んだ場合は1週間の変化として計算しません。

## 日付・単位・履歴

- 鮮度判定はダウンロード時刻ではなく観測日を使用します。初期基準はBTC価格・オンチェーン3暦日、金銀価格・ETF5暦日、CFTC10暦日です。
- `SPOT` / `FUTURES_PROXY` はUSD/トロイオンス、`ETF_PROXY`はUSD/口です。別の取得元・価格種類をつないだ架空の価格履歴を作りません。
- 1日につき同じ取得元の指標は1件です。同日再実行はupsertし、スコアから消えた構成要素も更新します。
- 画面と計算は共通のデータ選択処理を使用します。履歴は表示できますが、期限切れの値で現在フェーズを断定しません。
- 既存DBの追加カラムは自動移行し、履歴を削除しません。更新前に独自のDBコピーを取ることもできます。

履歴データの取り込み:

```bash
python scripts/backfill.py --asset btc --start 2020-01-01 --end 2026-09-01
python scripts/backfill.py --asset gold --start 2020-01-01 --end 2026-09-01
python scripts/backfill.py --asset silver --start 2020-01-01 --end 2026-09-01
```

この操作は観測データを保存します。過去の日次判定スナップショットを後付けで捏造する処理ではありません。

## 自動更新と検証

- `tests.yml`: push / PRで外部APIを使わない回帰テスト。空DB・既存DBの画面実行も含みます。
- `daily_update.yml`: 毎日07:45日本時間、手動実行、mainのソース変更後に更新します。
- 日次更新は直列実行です。DB・レポートのみのbotコミットから再帰的に更新を起動しません。
- ActionsのSummaryに、MVRV・価格・CFTC・GLD/IAU/SLVの取得状態を表示します。任意データの欠損も警告で確認できます。
- 主要価格が欠けた場合は前回公開済みDB・レポートを保持します。通常更新は `reports/latest.md` と `reports/archive/YYYY-MM-DD.md`、SQLite履歴を保存します。

```bash
python -m pytest -q
```

テストは、API権限拒否・ページ分割・スポンサーExcel/CSV/日付つきHTMLの解析・欠損・非有限値・価格系列の混在・古いデータの排除・DB保存・画面カード・日次レポートを検証します。外部APIの実際の提供状態は日次更新のSummaryで確認します。

このリポジトリのGitHub Actionsは、データとレポートを更新するものです。Streamlit画面を公開するホスティング自体は含みません。すでにStreamlit Community Cloud等でこのリポジトリのmainを接続している場合は、そのサービス側で更新を確認してください。
