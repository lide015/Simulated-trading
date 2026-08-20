# 台股全能 AI 決策系統(MVP)

> 設計依據:[`docs/taiwan-stock-ai-blueprint.md`](../docs/taiwan-stock-ai-blueprint.md)
> 範疇:里程碑 1(WP1 資料層＋WP3 事實表＋模組三本地訊號＋模組六 LINE 查詢)
> 與 repo 根目錄 `README.md`(加密貨幣模擬交易平台)是**兩個獨立專案**,不共用程式碼或資料庫。

## ⚠ 自用聲明(先讀這個)

本系統僅供開發者本人研究與自用查詢,**不對外開放、不收費、不作為投資建議**。
依《證券投資信託及顧問法》第 4、6 條,「取得報酬＋對不特定人＋提供個股分析
或推介」三要件齊備即構成非法經營證券投資顧問,可負刑責。自用完全合法;
**請勿公開 LINE Bot 的 webhook URL 或分享給不特定人使用**,也不要把訊號輸出
包裝成對外的投資建議服務。詳見藍圖文件「八、法遵紅線」。

所有訊號輸出一律使用描述性語言(「出現量增價漲」),不使用「建議買進」
之類的推介性語言——這是程式碼層面就刻意維持的紅線,不只是文件宣示。

## 架構

```
taiwan_stock_ai/
  config.py            設定值(環境變數 + .env)
  data/                 WP1 資料層:TWSE/TPEx OpenAPI + FinMind 備援
    http.py               共用 HTTP(重試/退避)+ RateLimiter
    twse_client.py         TWSE OpenAPI(日行情、三大法人、月營收、重大訊息、處置股)
    tpex_client.py         TPEx OpenAPI(上櫃日行情)
    finmind_client.py      FinMind 備援(600 次/小時節流)
    fetch_daily.py          每日批次協調器(單一資料源失敗不拖垮整批)
  storage/               WP3 事實表:DuckDB
    schema.sql             正規化事實表 schema
    db.py                   連線 + upsert(冪等,以複合主鍵防重複)
  signals/                模組三:本地訊號引擎(0 token)
    indicators.py            純 Python 技術指標(SMA、漲跌幅、滾動高低點)
    engine.py                 動量 + 均線糾纏突破偵測器,標【當沖】【波段】
  notify/                 模組六:LINE Bot 查詢(reply-only,0 token)
    templates.py              模板句庫
    queries.py                  規則 dispatcher(讀資料庫,不寫、不叫 LLM)
    line_bot.py                  FastAPI webhook + 簽章驗證
  scheduler/
    run_daily.py             單一進入點:抓取 → 落地 → 訊號引擎
```

## 本地開發

```bash
pip install -r requirements.txt
cp .env.example .env   # 依需要填 FinMind token / LINE 憑證,不填也能跑

# 跑一次完整的每日批次(抓取 + 落地 + 訊號引擎)
python -m taiwan_stock_ai.scheduler.run_daily

# 啟動 LINE webhook 開發伺服器
uvicorn taiwan_stock_ai.notify.line_bot:app --reload --port 8000

# 啟動前台/後台儀表板(前台公開看行情、後台密碼保護看事實表健康度/訊號/
# LINE 查詢預覽/DecisionRecord)
streamlit run dashboard/app.py

# 補歷史資料(FinMind,官方 OpenAPI 只有最新快照時用這個,見下方已知限制 1)
python -m taiwan_stock_ai.scheduler.backfill_history

# 跑測試(全部用合成資料,不打真實網路)
pytest tests/
```

## 已知限制(上線前必看)

1. **官方 OpenAPI 多數端點只回最新一期快照,沒有歷史查詢參數**——歷史深度
   要靠每天排程累積。想立刻有像樣的 K 線,用
   `taiwan_stock_ai/scheduler/backfill_history.py`(CLI 或
   `.github/workflows/backfill_history.yml` workflow_dispatch)——改走
   FinMind 的歷史區間查詢一次補回過去 N 天,預設自動選今天成交值最高的
   30 檔補 90 天。FinMind 是備援來源,這支程式刻意只能手動觸發,不會被
   排進每日 cron,不會取代 `twse_client` 當主要每日資料來源。
2. **TWSE/TPEx 的欄位名稱對映是依訓練資料撰寫,未經即時連線驗證**(開發
   當下沙盒環境的網路政策擋掉了對外部網域的連線)。上線前務必手動 `curl`
   一次每個端點,對照 `data/twse_client.py`、`data/tpex_client.py` 裡的
   `pick()` 候選欄位名稱是否正確;`fetch_daily.py` 會把 schema 對不上的
   資料集記成 `fetch_log.status='failed'`,不會靜默寫入垃圾資料。
3. **處置股清單用的是非正式 `/rwd/` 端點**,不在官方 Swagger 清單內,是
   目前最脆弱的一環,也是唯一直接影響合規安全網(當沖排除處置股)的資料
   源——抓取失敗時 `fetch_disposition_stocks()` 回傳 `None` 而非空清單,
   讓上游知道「不確定」而不是誤判「目前沒有處置股」。
4. **GitHub Actions cron 不知道台灣國定假日**,只用星期幾(一~五)過濾週
   末,遇到國定假日這次執行會是官方端點回傳「最新一期」(可能是前一個
   交易日)的資料,需要之後補上台股交易日曆判斷。
5. **DuckDB 事實表直接 commit 進 git**(`git add -f`),取代原報告建議延續
   的 Supabase——因為本 repo 一開始沒有可延續的 Supabase 專案。之後量體
   變大或要多處讀寫時,再依報告建議遷移到 Postgres/Supabase,`storage/db.py`
   的 upsert 介面設計成可替換。
6. **回測與 Deflated Sharpe Ratio 驗證不在本 MVP 範圍**——依報告的批判性
   結論,當沖策略在有誠實的 walk-forward + DSR 驗證前不應自動化,這是
   刻意的範疇切割,不是遺漏。
7. **DuckDB 檔案鎖是獨佔式的**:`dashboard/app.py` 一律用
   `read_only=True` 開連線,原因就是排程批次(`scheduler/run_daily.py`)
   跑的時候會拿到讀寫鎖,若儀表板此時也想用讀寫模式開同一個檔案會直接
   失敗。反過來,如果批次剛好在儀表板已經開著唯讀連線時啟動,批次那邊
   也可能連線失敗——兩者撞期的機率對個人排程來說很低,但如果真的遇到,
   重跑批次或重新整理儀表板頁面即可,不是資料損毀。
