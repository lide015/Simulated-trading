# Simulated Trading Platform

Tier 4 模擬交易平台 - 系統主動發現你沒問的問題

> 作者: Lide × Claude
> 狀態: MVP 階段 (可立即使用方案 1)

## 🎯 核心特性

- **DecisionRecord**: 每筆下單完整的決策結構化記錄
- **6 維標籤體系**: setup_type / key_level / indicator_trigger / context / trader_state / market_regime
- **24h 自動回填**: 系統自動記錄 outcome,無需人工合理化(規劃中,見下方「計畫」)
- **L7 Discovery Engine**: 主動掃描交易模式,提出假設讓你驗證(規劃中)
- **R-multiple 計分**: 跨 setup 可比的風險單位

## 🚀 快速開始 (3 分鐘)

### 1. 檢查環境

```bash
git clone https://github.com/lide015/Simulated-trading.git
cd Simulated-trading
pip install -r requirements.txt        # decision_writer.py 只需標準庫,這行是給之後要用 api_server.py 的人
python scripts/decision_writer.py --example  # 查看示例 JSON
```

### 2. 告訴 Claude 你的交易想法

```
我剛在 BTC 73850 做多單,停損 72900,目標 75500。
預期反彈,信心 4/5,冷靜。
市場狀態: 1h RSI 68,區間整理。

請生成 DecisionRecord JSON。
```

### 3. Claude 生成 JSON,你執行:

```bash
python scripts/decision_writer.py --json '{"id":"dec-2026-08-15-001",...}'
```

✅ 完成! 資料已寫入資料庫(預設 `trading.db`,可用 `DATABASE_PATH` 環境變數改路徑)

## 📖 詳細文件

- [完整規格](README.md) - 7 層架構、DecisionRecord 定義、L7 演算法
- [Claude 集成指南](docs/CLAUDE_INTEGRATION.md) - 3 種權限方案
- [資料庫 Schema](db/schema.sql) - 3 張表 (decisions / experiments / discovery_log)

## 🔄 工作流程概覽

```
你的交易決策
    ↓
告訴 Claude → Claude 生成 JSON
    ↓
python scripts/decision_writer.py --json '...'
    ↓
資料寫入 trading.db
    ↓ (24h 後,規劃中)
系統自動回填 post_outcome
    ↓
L6 歸因分析: 「我做 X setup 的勝率?」
    ↓
L7 Discovery: 「你沒注意到 Y 模式」
    ↓
Suggested Experiment: 「下週驗證這個假設」
```

## 📊 支援的命令

```bash
# 顯示示例 JSON
python scripts/decision_writer.py --example

# 寫入新決策
python scripts/decision_writer.py --json '{"id":"...",...}'

# 查看統計
python scripts/decision_writer.py --stats

# 列出已完成的決策 (已回填 outcome)
python scripts/decision_writer.py --list

# 讀取單筆記錄
python scripts/decision_writer.py --read "dec-2026-08-15-001"
```

## 🔐 權限模型

**方案 1 (推薦 MVP): Copy-Paste JSON**
- Claude 生成 JSON (無需 credentials)
- 你手動執行 Python (你的機器上)
- 零設定,立即可用

**方案 2 (自動化): GitHub Issue + Actions**
- 建 Issue → Actions 自動解析 → DB 自動更新
- 完全自動,有審計痕跡

**方案 3 (生產): FastAPI Server**
- REST API 端點
- 支援遠端呼叫,預設要求 `API_KEY`(見 [Claude Integration Guide](docs/CLAUDE_INTEGRATION.md))

👉 詳見 [Claude Integration Guide](docs/CLAUDE_INTEGRATION.md)

## 🖥 後台儀表板

```bash
streamlit run dashboard/app.py
```

一個唯讀的 Streamlit 儀表板,同時看得到這個 repo 裡兩個子專案的資料:

- **台股全能 AI 決策系統**(`taiwan_stock_ai/`):事實表健康度、訊號瀏覽、
  以及一個「LINE 查詢預覽」——直接呼叫 LINE Bot 用的同一套規則引擎,不用
  真的建 LINE 帳號就能看到查詢會回什麼。
- **DecisionRecord 平台**:決策清單、統計數字(勝率/平均 R)、R 值分布圖、
  單筆決策的完整 JSON。

只讀不寫,不會跟排程批次或 CLI 互搶資料庫鎖(細節見
`taiwan_stock_ai/README.md`「已知限制」)。

### 🔑 密碼保護

儀表板顯示的是交易決策細節,預設**拒絕顯示任何資料**,除非設定了
`DASHBOARD_PASSWORD`(fail-closed,不會有「忘記設定就變成裸奔」的風險):

```bash
# 本機開發
export DASHBOARD_PASSWORD="換成一組夠長的密碼"
streamlit run dashboard/app.py
```

本機也可以複製 `.streamlit/secrets.toml.example` 成 `.streamlit/secrets.toml`
填密碼(這個檔案已加進 `.gitignore`,不會被 commit)。

### 🌐 部署成網站(Streamlit Community Cloud)

Streamlit 官方免費託管,直接接這個 GitHub repo,repo 一有新 push 就自動
重新部署,跟現有架構天生契合。這一步需要用你自己的帳號登入 GitHub 授權,
沒辦法由 Claude 代勞,步驟如下:

1. 前往 [share.streamlit.io](https://share.streamlit.io),用 GitHub 帳號登入
2. 點「New app」,選這個 repo(`lide015/Simulated-trading`)、選分支
   (例如 `claude/taiwan-stock-ai-system-review-nse4e4` 或合併後的 `main`)、
   Main file path 填 `dashboard/app.py`
3. 部署前先點「Advanced settings」→「Secrets」,貼上:
   ```toml
   DASHBOARD_PASSWORD = "換成一組夠長的密碼"
   ```
4. 點 Deploy。網址預設是公開的(任何人都能打開登入頁),但沒有正確密碼
   看不到任何資料——這正是選「需要密碼保護」這個選項時要的效果。
5. 之後 `taiwan_stock_ai` 的每日批次(GitHub Actions)跟 `parse-decision.yml`
   都會把新資料 commit 回同一個 repo,Streamlit Cloud 偵測到 push 會自動
   重新部署,不用手動同步。

⚠ 免費方案沒有失敗登入次數鎖定,密碼要夠長;真的要更強的存取控制,之後
可以換成 `streamlit-authenticator`,或把 app 放到有存取控制的內部網路
(如 Tailscale/VPN)後面,不透過 Streamlit Cloud 公開網址。

## 📋 計畫

- [x] 資料庫 Schema (3 張表)
- [x] decision_writer.py CLI 工具
- [x] Claude 集成指南
- [x] Streamlit 儀表板 (MVP)
- [ ] L1-L3 實裝 (K 線 + 指標 + 訂單模擬)
- [ ] L4-L5 實裝 (持倉 + 績效統計)
- [ ] L6 實裝 (歸因引擎 + 24h 自動回填)
- [ ] L7 實裝 (Discovery Engine)

## 💬 範例

告訴 Claude:

```
我在 BTC/USDT 永續做了一筆交易:

時間: 現在
入場: 73850 (多)
止損: 72900 (1R = 950 USDT)
目標: 75500 (1.74R)
部位: 0.05 BTC
風險: 100 USDT

我的預測: 預期從 73000 支撐反彈
信心度: 4/5
情緒: 冷靜
設置類型: mean_reversion
市場狀態: ranging

市場快照:
- 1h RSI: 68 (超買)
- 1h MACD: 正向
- 1h ATR: 420
- 資金費率: 0.012% (偏高)
- 時段: 亞洲

請生成 DecisionRecord JSON。
```

Claude 輸出:

```json
{
  "id": "dec-2026-08-15-trading-001",
  "ts": "2026-08-15T14:30:00Z",
  "market_snapshot": {
    "price": 73850,
    "ohlcv_multi_tf": {
      "15m": [[1723729800, 73820, 73880, 73750, 73850, 1234.5]],
      "1h": [[1723726200, 73800, 73900, 73700, 73850, 8901.2]],
      "4h": [[1723713600, 73600, 73950, 73500, 73850, 23456.7]],
      "1d": [[1723664400, 72500, 74000, 72400, 73850, 234567.8]]
    },
    "indicators": {
      "1h": {"rsi": 68, "atr": 420, "macd_hist": 12.3},
      "4h": {"rsi": 55, "atr": 980, "macd_hist": 25.6}
    },
    "funding_rate": 0.00012,
    "session": "asia"
  },
  "trader_state": {
    "prediction_text": "預期從 73000 支撐反彈,看好 24h 內回升至 75000+",
    "confidence": 4,
    "reasoning_tags": {
      "setup_type": "mean_reversion",
      "key_level": "round_number",
      "indicator_trigger": ["rsi_overbought_1h"],
      "context": "ranging",
      "trader_emotion": "calm",
      "market_regime": "ranging"
    },
    "emotion": "calm"
  },
  "action": {
    "side": "long",
    "size": 0.05,
    "entry": 73850,
    "sl": 72900,
    "tp": 75500,
    "risk_amount": 100,
    "sl_distance_R": 1.0,
    "tp_distance_R": 1.74
  }
}
```

你執行:

```bash
python scripts/decision_writer.py --json '{...上面的 JSON...}'
```

✅ 決策已記錄到資料庫!

## 📈 下一步

1. 今天: 用方案 1 記錄 2-3 筆交易
2. 本週: 累積 10+ 筆 DecisionRecord
3. 下週: 升級到方案 2 (GitHub Actions)
4. 兩週後: 執行第一次歸因分析
5. 一個月後: L7 Discovery 上線,系統主動發現模式

## 📞 支援

- 問題 → 開 Issue
- 想法 → Discussions
- Claude 集成 → 見 [docs/CLAUDE_INTEGRATION.md](docs/CLAUDE_INTEGRATION.md)

讓資料找你,而不是你找資料。 🚀
