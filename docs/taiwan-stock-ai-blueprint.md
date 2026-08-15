# 鼎曜資本「台股全能 AI 決策系統」升級版技術藍圖與批判性審查報告

> 狀態:設計凍結 / MVP 實作中
> 對應分支:`claude/taiwan-stock-ai-system-review-nse4e4`
> 範疇說明:本文件所述系統與 repo 既有 `README.md`(加密貨幣模擬交易平台規格)為兩個獨立專案,程式碼位於 `taiwan_stock_ai/` 目錄下,不與既有平台共用資料庫或程式碼。

---

## MVP 範疇決策(第 0 條,凌駕全文)

依本報告「十一、蘇格拉底式批判」的結論,**里程碑 1(MVP)只做以下四項**,其餘全部延後:

1. **WP1 資料層**:TWSE / TPEx OpenAPI(官方、免金鑰)+ FinMind(備援,600 次/小時)
2. **WP3 事實表**:DuckDB 正規化事實表,(日期＋股號＋資料集)為唯一鍵 upsert
3. **模組三本地訊號引擎(0 token)**:先做動量與均線兩個訊號,標【當沖】【波段】【中長線】
4. **模組六 LINE 查詢**:reply-only,「2330」查訊號、「今日當沖選股」查清單

明確排除於 MVP 之外(達成上述門檻後才評估是否要做):模組二新聞情感、模組四總經關聯、LLM 多分析師辯論、回測框架(vectorbt/DSR)、Next.js 前端。理由:六大模組同時開對可用時間是致命的;當沖策略在有誠實的 walk-forward + Deflated Sharpe Ratio 驗證前不應自動化。

---

## TL;DR

- **核心判斷**:技術路線正確,但範圍過寬、順序有誤。既有「規則引擎＋模板句庫(零 token)」為主、LLM 只做三處插話的定案,是全案最正確的決策,應堅守;但六大模組同時開,對一個 20 歲上班族的可用時間是致命的。應砍到「資料層＋事實表＋當沖訊號＋LINE 查詢」的 MVP,其餘延後。
- **當沖策略期望值需誠實面對**:現股當沖證交稅減半(1.5‰)已三讀延長至 2027/12/31,但這只是降低成本、非提供 alpha;新聞情感分析對「隔日開盤」的預測力在實證文獻上證據薄弱(多數研究支持短期效率市場假說),開盤八法、九轉序列、RSI/MACD 背離皆為低證據強度指標,回測必須用 Deflated Sharpe Ratio 對抗過度擬合。
- **免費資料源 2026 現況可行但有陷阱**:官方 TWSE/TPEx/TAIFEX OpenAPI 免金鑰可用但多為「最新快照、無歷史」;FinMind 免費版限 600 次/小時且部分資料集已改為付費;yfinance 台股資料品質不穩、常因 Yahoo 改版失效,只能當備援;新聞爬蟲有明確著作權與服務條款風險,只能存 URL＋標題＋短摘要。

## Key Findings

1. 零 token 架構是對的,但要抓成本量級。全量運行的 LLM 成本,若嚴守「規則引擎為主、LLM 僅摘要/總結」,每月落在個位數到低雙位數美金;若濫用 LLM 逐檔逐新聞跑,會放大 10–50 倍。GPT-4o-mini 與 Claude Haiku 搭配 prompt caching(快取讀取為基礎輸入價的 0.1×,即省 90%)＋Batch API(輸入與輸出皆 50% 折扣、24 小時內完成,且與快取折扣可疊加)是關鍵槓桿。
2. 回測框架選 vectorbt(研究掃參)＋backtesting.py(單策略驗證),Backtrader 原作者自 2018 已停止主要開發,僅社群維護 bugfix,不建議作為新專案主力。回測致命錯誤(look-ahead、漲停無法成交、當沖成本、過度擬合)必須以 walk-forward＋Deflated Sharpe Ratio 制度化防守。
3. 資料庫:延續 Supabase(Postgres),本地加 DuckDB 做事實表分析、pgvector 做 RAG,不必為了 ChromaDB/Qdrant 另起爐灶。中文金融 embedding 首選 BGE-M3(多語、8K 長度、dense+sparse+多向量、CPU 可跑)。
4. 當沖制度:證交稅減半 1.5‰ 延至 2027/12/31;處置股不可當沖、採分盤集合競價(5 分/20 分搓合)＋預收圈存,回測必須排除處置期間並對警示股加大滑價假設。
5. 法遵紅線清楚:依《證券投資信託及顧問法》第 4、6 條,「取得報酬＋對不特定人＋提供個股分析或推介」三要件齊備即構成非法經營投顧,可負刑責。自用完全合法;一旦對外提供(尤其收費),風險陡增。

## Details

### 一、免費資料源 2026 真實現況

**官方交易所 OpenAPI(首選,免金鑰、免註冊、合法)**

- TWSE 證交所 OpenAPI:`https://openapi.twse.com.tw/`(Swagger)。HTTP GET 回 JSON 陣列,約 140+ 端點。共通限制:日期為民國年字串;多數端點只回「最新一期快照」,無歷史查詢參數,歷史要自己每日抓存。無明確速率標頭,建議自行節流＋重試＋快取。
- TPEx 櫃買中心 OpenAPI:`https://www.tpex.org.tw/openapi/`。上櫃資料獨立一套,欄位命名與上市不一致(上市多中文欄名、上櫃多英文欄名),跨市場需自建對映表。
- TAIFEX 期交所:`openapi.taifex.com.tw` 僅提供最新一個交易日;三大法人、大額交易人未平倉等歷史需從 `www.taifex.com.tw` 下載頁(如 `/cht/3/futContractsDate`、`/cht/3/largeTraderFutQry`)解析。大額交易人未平倉資料自 2012/5/1 起提供交易日前三年查詢,更早需填公開資料申購表。
- MOPS 公開資訊觀測站:入口 `mops.twse.com.tw`(鏡像 `mopsov.twse.com.tw`)為表單 POST、有 referer/session 反爬。官方機器路徑改走 TWSE OpenAPI:每月營收 `/v1/opendata/t187ap05_L`、公司基本資料 `/v1/opendata/t187ap03_L`、重大訊息 `/v1/opendata/t187ap04_L`。欄位為繁中 JSON key、民國年。多為最新快照,歷史自行累積。(註:舊版 MOPS 內部表單代碼「t05st10」已由 OpenAPI 正規端點 t187ap05_L 取代。)
- TDCC 集保股權分散表:查詢頁 `https://www.tdcc.com.tw/portal/zh/smWeb/qryStock`;開放資料 `https://opendata.tdcc.com.tw/getOD.ashx?id=1-5`(CSV,每週更新,以各集保戶每週最後營業日餘額 ID 歸戶編制)。政府開放平台亦有鏡像(data.gov.tw/dataset/11452)。

**第三方套件(備援,有限制)**

- FinMind:`https://finmindtrade.com/`。依官方 quickstart:免費 300/hr,註冊並驗證信箱後加 token 可提高到 600/hr;部分資料集(一次抓特定日期全市場、部分籌碼/逐筆)已限付費贊助帳戶。資料每日更新、來源證交所。適合快速起步與交叉驗證,勿當唯一來源。
- twstock:`https://github.com/mlouielu/twstock`。TWSE 有請求限制:每 5 秒 3 個 request,超過會被 ban。維護狀態一般、端點偶因 TWSE 改版失效,建議只用其代碼表與輔助函式。
- yfinance:台股用 `.TW`(上市)/`.TWO`(上櫃)後綴。財務資料常缺、Yahoo 改版就整包失效,高頻抓取易被擋。定位為「最後備援」,勿作當沖即時來源。

**新聞來源合法性**

- 鉅亨網 Anue:無官方 API/RSS;服務條款明文禁止未經書面授權之重製、改作、公開傳輸、散布。風險最高,不可存全文。
- 經濟日報 money.udn.com:有官方 RSS(`https://money.udn.com/rssfeed/lists/1001`),適合合規抓標題與連結。
- 工商時報 ctee.com.tw:無確認官方 RSS,全權利保留。
- 合規建議:只存 URL＋標題＋機器產生的短摘要＋時間戳＋來源標註,回連原文;不存全文、不轉貼圖片。優先用有官方 RSS 者(自由時報 service.ltn.com.tw/RSS、中央社 focustaiwan 可作合規補充)。

### 二、當沖與交易制度 2026 現行規則

- 證交稅減半:現股當沖證交稅由 3‰ 降至 1.5‰,施行期限延長至 116 年(2027)12 月 31 日止;2025/1/4 生效。這是成本項、非 alpha。
- 注意→警示→處置:處置股採分盤集合競價(第一次約 5 分鐘、第二次約 20 分鐘搓合一次)＋預收款券圈存;處置期間不可當沖。當沖占比過高會被列注意;因漲跌幅處置又當沖比過高,處置期由 10 延為 12 個營業日。
- 回測意涵:必須排除處置期間標的、對警示/注意股加大滑價與流動性折價、對漲停/跌停 bar 設「無法成交」旗標。

### 三、資料庫與向量庫、embedding 選型

- 時序/事實表:雲端事實表用 Postgres(Supabase);本地重運算用 DuckDB(欄式、單檔、pandas 原生、掃 K 線與因子極快)。MVP 階段先只用 DuckDB(見下方「MVP 落地時的取捨」)。
- 向量庫:pgvector(若已在 Postgres)或 ChromaDB(純本地離線)。MVP 不需要,列為延後項目。
- 中文金融 embedding:BGE-M3(BAAI)為首選。延後項目。

### 四、回測框架與陷阱

- 框架:vectorbt(掃參)＋backtesting.py(單策略驗證)。Backtrader 已停止主要開發。
- 致命錯誤清單:look-ahead bias、survivorship bias、還原權值處理、漲跌停無法成交、當沖成本低估、過度擬合、多重檢定。
- 對抗過度擬合:Deflated Sharpe Ratio(Bailey & López de Prado, 2014, *Journal of Portfolio Management* 40(5): 94–107)、walk-forward、out-of-sample;新因子 t 值門檻提高到 3.0(Harvey, Liu & Zhu, 2016, *Review of Financial Studies* 29(1): 5–68)。此為里程碑 2 工作,MVP 階段先不做自動化回測,僅做離線驗證。

### 五、技術指標正確性與證據強度

- 開盤八法、九轉序列(TD Sequential)、RSI/MACD 背離:皆為低證據強度的啟發式指標,可作可解釋的情境標籤與規則引擎組件,**不宣稱有預測 alpha**。
- 量增價強動量:相對有實證基礎(動量因子),當沖層級雜訊高、成本吃掉大半期望值,故 MVP 訊號仍需搭配保守的規則(如排除處置股、加入流動性門檻)。
- MVP 訊號引擎採用「動量」與「均線糾纏突破」兩個訊號,理由:證據相對最強、實作最簡單、可解釋性最高。

### 六、LLM 成本最小化架構(延後至里程碑 3)

- 模型分工、prompt caching、Batch API、本地小模型等策略,詳見原文;MVP 完全不呼叫 LLM(0 token),LINE 查詢與訊號輸出全部走規則引擎＋模板句庫。

### 七、第三方平台官方 Console/申請網址

- LINE Developers Console:`https://developers.line.biz/console/`。Messaging API 建 channel、取 channel access token、設 webhook。免費 200 則/月,reply 免費不計額度。
- Gmail SMTP(應用程式密碼):`https://myaccount.google.com/apppasswords`(延後,MVP 不含日報)。
- FinMind 註冊:`https://finmindtrade.com/`

### 八、法遵紅線(自用聲明)

自用完全合法;一旦「對不特定人＋收報酬＋提供個股分析或推介」三要件齊備,即構成非法經營證券投資顧問(《證券投資信託及顧問法》第 4、6 條),可負刑責。本系統(含 LINE Bot)僅供開發者本人研究與自用查詢,不對外開放、不收費、不作為投資建議。

## MVP 落地時的取捨(相對原報告的調整)

- **資料庫**:原報告建議「延續 Supabase」,但本 repo 目前無任何既有資料庫或憑證可延續。MVP 選擇 **DuckDB 單檔本地資料庫**,原因:免服務申請、免憑證、符合報告本身對 DuckDB 的背書(欄式、事實表分析快)。之後要接 Supabase/Postgres 時,`storage/` 層的 upsert 介面設計為可替換。
- **回測與 DSR 驗證**:歸為里程碑 2,MVP 不含自動回測管線,避免「六大模組同時開」的錯誤重演。
- **新聞情感、總經關聯、多分析師辯論、Next.js 前端**:明確排除於本次實作範圍。

## 里程碑與觸發門檻(節錄自原報告 Recommendations)

| 階段 | 內容 | 觸發下一階段門檻 |
|---|---|---|
| 階段 0 | 資料層＋事實表＋自用聲明 | 連續 5 個交易日零缺漏、schema 校驗通過 |
| 階段 1 | 本地訊號＋回測誠實化(DSR) | 策略 out-of-sample DSR > 0(扣成本後正期望) |
| 階段 2 | LINE Bot＋通知 MVP | 連續 2 週查詢延遲 < 3 秒、零漏送 |
| 階段 3 | 敘事層(規則引擎辯論)＋LLM 插話 | 證據達標才做(新聞情感、總經關聯) |

---

*本文件為原始批判性審查報告的存檔版本,供後續實作對照決策依據;內文之技術指標、法規時效請以官方最新資訊為準(原文「Caveats」章節）。*
