# Claude Integration Guide - 讓 Claude 直接寫入你的資料庫

## 🎯 核心概念

Claude 無法直接存取你的本機檔案系統或資料庫,但可以透過以下方式寫入:

**三層權限模型:**

```
┌─────────────────────────────────────────────────┐
│ Layer 1: Claude 生成 JSON (無需權限)              │
│      → DecisionRecord 格式化輸出                  │
└──────────────────┬──────────────────────────────┘
                    │
┌──────────────────▼──────────────────────────────┐
│ Layer 2: 你執行命令 (本機權限)                     │
│      → paste JSON → run Python script → 寫入 DB  │
└──────────────────┬──────────────────────────────┘
                    │
┌──────────────────▼──────────────────────────────┐
│ Layer 3: 自動化工作流 (GitHub Actions 權限)        │
│      → GitHub Issue → Actions → DB                │
└─────────────────────────────────────────────────┘
```

---

## 方案 1️⃣: 最簡單 - Copy-Paste JSON (推薦 MVP)

### 步驟:

**1. 告訴 Claude 你要記錄一筆交易:**

```
我剛才在 BTC 73850 做了一筆 mean_reversion 多單,停損 72900,目標 75500。
預期會反彈,信心度 4/5。
市場狀態: 1h RSI 68 (overbought),正在 ranging。
請生成 DecisionRecord JSON。
```

**2. Claude 會輸出:**

```json
{
  "id": "dec-2026-08-15-001",
  "ts": "2026-08-15T14:30:00Z",
  "market_snapshot": {...},
  "trader_state": {...},
  "action": {...}
}
```

**3. 你執行這個命令 (複製 JSON 部分):**

```bash
python scripts/decision_writer.py --json '{"id":"dec-2026-08-15-001",...}'
```

✅ 完成! 資料已寫入 `trading.db`

**優點:**
- ✅ 零設定,立即可用
- ✅ 完全控制,可在執行前檢查數據
- ✅ Claude 無需任何 credentials

**缺點:**
- ❌ 需要手動 copy-paste
- ❌ 如果想自動化需升級

---

## 方案 2️⃣: 進階 - GitHub Issue 作為中間層

### 架構:

```
Claude 生成 JSON
    ↓ (貼到 Issue)
GitHub Issue (帶 decision-record 標籤)
    ↓
GitHub Actions Workflow (自動觸發)
    ↓
Python Script (讀取 Issue,寫入 DB)
    ↓
✅ 資料自動入庫
```

### 設定步驟:

已內建於本 repo:
- Issue 範本:[`.github/ISSUE_TEMPLATE/decision-record.md`](../.github/ISSUE_TEMPLATE/decision-record.md)
- 自動解析 workflow:[`.github/workflows/parse-decision.yml`](../.github/workflows/parse-decision.yml)

workflow 從 Issue 內文擷取 ```` ```json ... ``` ```` 區塊、驗證是合法 JSON 後才呼叫
`scripts/decision_writer.py --json`,寫入成功才 commit `trading.db` 並 push——刻意不把
Issue 內文直接接進 shell 指令字串(那是常見的 GitHub Actions script-injection 漏洞),
而是用環境變數 + Python 解析,失敗就整個 job fail,不會把壞資料寫進資料庫。

### 使用方式:

1. 告訴 Claude:

```
幫我生成 DecisionRecord JSON,格式要能貼到 GitHub Issue。
```

2. Claude 輸出 JSON
3. 你在 GitHub 用「Decision Record」範本建立 Issue,把 JSON 貼進 ```` ```json ``` ```` 區塊
4. GitHub Actions 自動:
   - ✅ 解析並驗證 JSON
   - ✅ 執行 decision_writer.py
   - ✅ 提交到 repo
   - ✅ 資料自動入庫

**優點:**
- ✅ 自動化,無需手動命令
- ✅ 有審計痕跡 (Issue history)
- ✅ 可以在 Issue 裡討論決策

**缺點:**
- ⚠️ 需要設定 GitHub Actions
- ⚠️ Actions 需要 `contents: write` 權限(見 workflow 的 `permissions:` 區塊)

---

## 方案 3️⃣: 最強大 - REST API (生產環境)

### 設定:

`scripts/api_server.py` 已經是一支可以直接跑的 FastAPI 服務,基於同一套
`DecisionWriter` / `create_decision_from_dict`(來自 `scripts/decision_writer.py`,
不是另外重寫一份邏輯):

```python
from fastapi import FastAPI, Header, HTTPException
from decision_writer import DecisionWriter, create_decision_from_dict, DEFAULT_DB_PATH
import os

API_KEY = os.getenv("API_KEY", "")
app = FastAPI(title="Simulated Trading API")
writer = DecisionWriter(os.getenv("DATABASE_PATH", DEFAULT_DB_PATH))

@app.post("/decisions")
def create_decision(payload: dict, x_api_key: str | None = Header(default=None)):
    """
    建立一筆新的決策記錄。

    Example:
    POST /decisions
    {
      "market_snapshot": {...},
      "trader_state": {...},
      "action": {...}
    }
    """
    ...
```

完整實作見 [`scripts/api_server.py`](../scripts/api_server.py)。

啟動伺服器:

```bash
python scripts/api_server.py
```

Claude 可以這樣調用:

```bash
curl -X POST http://localhost:8000/decisions \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d '{...json payload...}'
```

**優點:**
- ✅ 完全自動化
- ✅ 可遠端呼叫
- ✅ 便於整合其他系統

**缺點:**
- ⚠️ 需要伺服器運行
- ⚠️ 需要驗證 (見下方「安全性考慮」)

---

## 🔐 安全性考慮

⚠️ **Claude 不應有直接的:**
- ❌ 資料庫密碼
- ❌ API Keys
- ❌ GitHub Tokens (在 Claude 可見的地方)

✅ **安全做法:**

1. **本機執行 (方案 1-2)**
   - Claude → JSON (文本)
   - 你 → 執行 Python (你的機器上)
   - 你掌控所有 credentials

2. **GitHub Actions (方案 2)**
   - 使用 GitHub 的 built-in `GITHUB_TOKEN`
   - 自動生成,無需手動設定
   - Issue 內文一律當作不可信輸入處理,不直接接進 shell 字串

3. **API Server (方案 3)**
   - 預設監聽 `127.0.0.1`(不是 `0.0.0.0`),避免不小心對外暴露
   - 設定 `API_KEY` 環境變數後,所有端點都要求 `X-API-Key` header 才放行
   - **沒設 `API_KEY` 時伺服器會在啟動時印警告**,並且只適合本機開發用途,不要對外公開

---

## 📝 推薦工作流程

**第 1-2 週 (MVP): 方案 1**

```
每天早上 9-11am:
  1. 觀察市場 + 做決策
  2. 告訴 Claude 你的想法
  3. Claude 生成 JSON
  4. 你 copy-paste 到命令行
  5. python scripts/decision_writer.py --json '...'

這時你已累積 30+ 筆 DecisionRecord
```

**第 2-4 週: 升級到方案 2**

```
設定 GitHub Actions workflow(已內建,見上方連結)
從此:
  1. 告訴 Claude 交易決策
  2. Claude 生成 JSON
  3. 你在 GitHub 建立 Issue
  4. Actions 自動執行 → DB 自動更新

0 手動命令,純自動化
```

**第 4 週+: 方案 3 (如需遠端調用)**

```
部署 FastAPI server(記得設定 API_KEY)
Claude 可以跨互聯網直接調用
```

---

## 🚀 立即開始 (方案 1)

**1️⃣ 檢查環境:**

```bash
# 進入 repo
cd Simulated-trading

# 檢查 Python
python --version  # 需要 3.9+

# 測試 decision_writer
python scripts/decision_writer.py --example
```

**2️⃣ 告訴 Claude:**

```
我在 Simulated-trading repo 裡設定好了。
現在我要記錄一筆交易決策。

交易詳情:
- 商品: BTC/USDT (永續)
- 方向: 多頭 (Long)
- 入場價: 73850
- 止損: 72900
- 目標: 75500
- 部位: 0.05 BTC
- 風險: 100 USDT (1R)

預測: 預期觸及 73000 支撐後反彈,看好 24h 內回升

市場狀況:
- 1h: RSI 68 (超買), MACD 正向, ATR 420
- 4h: 區間整理狀態
- 資金費率: 0.012% (偏高)
- 時段: 亞洲盤

我的信心度: 4/5
情緒: 冷靜

請生成 DecisionRecord JSON,讓我用這個命令寫入:
python scripts/decision_writer.py --json '<JSON_HERE>'
```

**3️⃣ Claude 生成 JSON**

**4️⃣ 你執行:**

```bash
python scripts/decision_writer.py --json '{...paste from Claude...}'
```

**5️⃣ 檢查:**

```bash
# 查看統計
python scripts/decision_writer.py --stats

# 列出已完成的決策
python scripts/decision_writer.py --list

# 讀取單筆記錄
python scripts/decision_writer.py --read "dec-2026-08-15-001"
```

---

## 📚 相關文件

- [`scripts/decision_writer.py`](../scripts/decision_writer.py) - CLI 工具
- [`scripts/api_server.py`](../scripts/api_server.py) - REST API(方案 3)
- [`db/schema.sql`](../db/schema.sql) - 資料庫 schema
- [`README.md`](../README.md) - 完整規格 (DecisionRecord 定義)
- [`README_QUICK_START.md`](../README_QUICK_START.md) - 3 分鐘快速開始

## 💡 下一步

- [x] 方案 1 - 手動 copy-paste (今天就能用)
- [x] 方案 2 - GitHub Actions (已內建 workflow,可直接用)
- [x] 方案 3 - FastAPI Server (可選,記得設定 `API_KEY` 再對外開)

問題? 在 Issue 裡討論,或直接問 Claude! 🚀
