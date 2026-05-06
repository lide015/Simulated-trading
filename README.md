# 強大模擬交易平台 — 完整規格文件

> 作者:Lide × Claude(Socratic 對話蒸餾)
> 版本:v1.0
> 日期:2026-05-06
> 狀態:設計凍結 / 等待實作

---

## 0. 這份文件存在的目的

把 6 輪 Socratic 對話的成果**凍結成藍圖**,讓未來的你或協作者可以:

1. 在不重複思考過程的情況下,直接動手實作
2. 在 3 個月後回頭看,記得**為什麼**每個設計選擇是這樣
3. 拒絕未來自己「想再加一個小功能」的衝動——所有偏離都應該有書面理由

---

## 1. 設計哲學:Tier 4

### 1.1 能力分層(對標市面工具)

| Tier | 能力 | 代表工具 |
|---|---|---|
| 1 | K 線 + 下單 + 盈虧 | TradingView Paper、各種 demo 帳號 |
| 2 | + 策略回測 + 多時間框架 + 指標庫 | Backtrader、QuantConnect |
| 3 | + 決策快照 + 多維標籤 + 歸因 | 極少數量化基金內部工具 |
| **4** | **系統主動發現你沒問的問題** | **本平台** |

### 1.2 一句話定義「強大」

> Tier 1-3 是**你查資料**(passive analytics)
> Tier 4 是**資料找你**(active discovery)

### 1.3 三條不可妥協的原則

1. **每一筆下單必須產生結構化的 DecisionRecord**——沒有快照,就沒有學習
2. **outcome 必須由系統自動回填**——不依賴人工,因為人會合理化
3. **每週至少一次主動 Discovery**——平台沉默 = 平台失效

---

## 2. 七層架構總覽

```
┌──────────────────────────────────────────────┐
│  L7: Discovery Engine                        │
│      Hidden Correlation Scanner              │
│      Meta-skill Diagnostics                  │
│      Regime Decay Detector                   │
│      → Suggested Experiments                 │
└──────────────────────────────────────────────┘
                       ▲
┌──────────────────────────────────────────────┐
│  L6: Learning Engine                         │
│      DecisionRecord (核心資料結構)            │
│      6 維標籤體系                             │
│      R-multiple 計分                         │
│      24h 自動回填 + 歸因引擎                  │
└──────────────────────────────────────────────┘
                       ▲
┌──────────────────────────────────────────────┐
│  L5: 反饋層                                   │
│      P&L、勝率、最大回撤、Sharpe              │
└──────────────────────────────────────────────┘
                       ▲
┌──────────────────────────────────────────────┐
│  L4: 持倉管理                                 │
│      多空追蹤、已實現 + 未實現盈虧            │
└──────────────────────────────────────────────┘
                       ▲
┌──────────────────────────────────────────────┐
│  L3: 訂單模擬引擎                             │
│      市價/限價/停損 + 滑點 + 手續費           │
└──────────────────────────────────────────────┘
                       ▲
┌──────────────────────────────────────────────┐
│  L2: 指標引擎                                 │
│      RSI/ATR/MACD/BB + 多時間框架同步        │
└──────────────────────────────────────────────┘
                       ▲
┌──────────────────────────────────────────────┐
│  L1: 資料層                                   │
│      WebSocket 即時 K 線 + SQLite 持久化      │
└──────────────────────────────────────────────┘
```

### 2.1 工作量地圖

| Layer | 內容 | MVP 工作量 | 複雜度 |
|---|---|---|---|
| L1 | WebSocket + SQLite | 1 天 | 低 |
| L2 | 指標引擎(用 ta-lib) | 0.5 天 | 低 |
| L3 | 訂單模擬 + 滑點 | 1 天 | 中 |
| L4 | 持倉管理 | 1 天 | 中 |
| L5 | 績效統計 | 1 天 | 低 |
| **L6** | **Decision Attribution Engine** | **3 天** | **高** |
| **L7** | **Discovery Engine** | **2-3 天** | **高** |

L6 + L7 ≈ L1-L5 加總。**這就是強大 vs 平庸的工作量分水嶺**。

---

## 3. 核心資料結構

### 3.1 DecisionRecord (整個平台的心臟)

```python
@dataclass
class DecisionRecord:
    id: str                   # uuid
    ts: str                   # ISO 8601, UTC

    market_snapshot: dict     # 來自 L1 + L2,下單瞬間的市場狀態
    trader_state: dict        # 你的預測 + 信心 + 標籤,事前必填
    action: dict              # 來自 L3,下單動作
    post_outcome: dict = None # 24h 後系統自動回填,事後鎖定
```

#### 3.1.1 market_snapshot 內容

```json
{
  "price": 73850,
  "ohlcv_multi_tf": {
    "15m": [...50 根 K 棒],
    "1h":  [...50 根 K 棒],
    "4h":  [...50 根 K 棒],
    "1d":  [...50 根 K 棒]
  },
  "indicators": {
    "1h": {"rsi": 68, "atr": 420, "macd_hist": 12.3},
    "4h": {"rsi": 55, "atr": 980}
  },
  "orderbook_depth": {...},
  "funding_rate": 0.012,
  "session": "asia"        // 自動推導
}
```

#### 3.1.2 trader_state 內容

```json
{
  "prediction_text": "預期回測 73000 後反彈",
  "confidence": 4,
  "reasoning_tags": {
    "setup_type": "mean_reversion",
    "key_level": "round_number",
    "indicator_trigger": ["rsi_oversold_1h"],
    "trader_emotion": "calm",
    "market_regime": "ranging"
  }
}
```

#### 3.1.3 action 內容

```json
{
  "side": "long",
  "size": 0.05,
  "entry": 73850,
  "sl": 72900,
  "tp": 75500,
  "risk_amount": 100,        // USDT,1R 的具體值
  "sl_distance_R": 1.0,      // 1R
  "tp_distance_R": 1.74      // 1.74R
}
```

#### 3.1.4 post_outcome 內容

```json
{
  "filled_at": ...,           // 系統 24h 後填
  "exit_price": ...,
  "exit_reason": "tp_hit",   // tp_hit | sl_hit | timeout | manual
  "pnl_R": +1.74,            // 用 R 為單位
  "pct_change": +0.022,
  "prediction_correct": true,
  "price_after_24h": ...,
  "max_favorable_excursion_R": +1.9,  // 最有利
  "max_adverse_excursion_R": -0.3     // 最不利
}
```

### 3.2 6 維標籤體系

#### 3.2.1 全貌

```yaml
SETUP_TYPE (必選 1):
  mean_reversion        # 反轉
  trend_continuation    # 順勢
  range_play            # 區間
  breakout              # 突破
  breakout_retest       # 突破回測

KEY_LEVEL (選 0-1):
  prev_day_high
  prev_day_low
  round_number          # 70k, 75k 整數
  horizontal_support
  horizontal_resistance

INDICATOR_TRIGGER (選 0-2):
  rsi_oversold_1h
  rsi_overbought_1h
  rsi_divergence
  macd_cross_bull
  macd_cross_bear
  bb_lower_touch
  bb_upper_touch
  atr_expansion

CONTEXT (系統自動填,你不用打):
  session_asia / eu / us
  funding_high           # > +0.05%
  funding_negative       # < 0
  volatility_high        # ATR > 90 day MA × 1.3
  volatility_low

TRADER_STATE (事前必填):
  confidence_1 ~ confidence_5
  emotion_calm
  emotion_anxious
  emotion_fomo
  emotion_revenge

MARKET_REGIME (系統半自動,你 confirm):
  ranging                # ATR 收縮 + 高低點堆疊
  trending_up            # HH+HL
  trending_down          # LH+LL
  pre_breakout           # ATR 收縮 + 區間壓縮
  post_breakout          # ATR 放大
```

#### 3.2.2 5 鐵則

##### 鐵則 1:標籤分維度,不要平鋪

平庸做法把所有標籤丟在一個 list,後面交叉分析會崩。
強大做法是固定 N 個維度,每個維度互斥,可交叉統計。

##### 鐵則 2:描述性 vs 解釋性 分開

- **描述性**(描述市場,如 `rsi_oversold`):可從 market_snapshot 自動推導
- **解釋性**(解釋為何下單,如 `mean_reversion_play`):**必須人工填**——學習價值在這

##### 鐵則 3:事前必填、事後鎖定

下單前強制填寫,下單後鎖死。否則人會在虧錢後改標籤合理化自己——系統就毀了。

##### 鐵則 4:禁止「結果預測型」標籤

❌ `bullish`, `should_pump`, `probably_up`
✅ `mean_reversion_play`, `range_long`

帶結果預測的標籤事後一定跟結果重疊,統計就 trivial 了。

##### 鐵則 5:演進式分類學

| 階段 | 標籤策略 |
|---|---|
| 第 1 月 | 5-7 個粗標籤,廣泛使用 |
| 第 2 月 | 高頻拆細,低頻合併 |
| 第 3 月 | 穩定下來 |

固定的標籤體系一定會死。市場會變,你的觀察會變,標籤要能演化。

### 3.3 R-multiple 計分制

#### 3.3.1 為什麼用 R 不用 %

```
勝率 70%、平均賠率 1:0.5  → EV = 0.7×0.5 - 0.3×1 = +0.05
勝率 40%、平均賠率 1:3    → EV = 0.4×3   - 0.6×1 = +0.60
```

第二個賺 12 倍,但勝率比較會誤導你選第一個。**R-multiple 是 setup 之間的共通語言**。

#### 3.3.2 強制欄位

下單時必填:
- `risk_amount`(USDT,固定金額,如 100)
- `sl_distance`(entry → sl 的價格距離,= 1R 的具體值)
- `tp_distance`(entry → tp 的價格距離,= 幾 R)

outcome 用 R 記錄(`pnl_R = +2.3R`),所有 setup 之間直接可比。

### 3.4 三張資料表

```sql
-- 主表:每筆下單一筆
CREATE TABLE decisions (
  id TEXT PRIMARY KEY,
  ts TEXT NOT NULL,
  market_snapshot JSON,
  trader_state JSON,
  action JSON,
  post_outcome JSON,         -- 24h 後填,在此之前為 NULL
  is_locked BOOLEAN DEFAULT TRUE  -- 鎖定,不可改
);

CREATE INDEX idx_ts ON decisions(ts);
CREATE INDEX idx_setup ON decisions(json_extract(trader_state, '$.reasoning_tags.setup_type'));
CREATE INDEX idx_regime ON decisions(json_extract(trader_state, '$.reasoning_tags.market_regime'));

-- 實驗表:L7 提的假設 + 你的驗證結果
CREATE TABLE experiments (
  id TEXT PRIMARY KEY,
  proposed_at TEXT,
  hypothesis TEXT,            -- 假設文字
  conditions JSON,            -- 觸發條件 (如: funding < 0)
  target_n INTEGER,           -- 需要幾筆樣本
  status TEXT,                -- proposed | active | concluded
  conclusion TEXT,            -- 驗證結果
  related_decision_ids JSON   -- 涉及的下單 id 清單
);

-- Discovery 自身 log:防止 L7 自己 overfit
CREATE TABLE discovery_log (
  id TEXT PRIMARY KEY,
  detected_at TEXT,
  type TEXT,                  -- correlation | meta_skill | decay
  pattern_description TEXT,
  p_value REAL,
  effect_size REAL,
  n_samples INTEGER,
  hit_or_miss BOOLEAN         -- 後續驗證,該 pattern 是否真的成立
);
```

---

## 4. L1-L5 規格(傳統紙交易部分)

### 4.1 L1 資料層

**職責**:即時 K 線 + 訂單簿 + funding rate + 持久化

**技術選擇**:
- 交易所:Binance(現貨 + 永續)
- 連接:`ccxt.pro` (WebSocket) + `ccxt` (REST 補拉)
- 持久化:SQLite(MVP),時序資料 9 個月後可考慮升 InfluxDB

**核心介面**:
```python
class MarketData:
    def stream_ohlcv(symbol, tf, callback): ...
    def fetch_ohlcv(symbol, tf, since, limit): ...
    def snapshot_multi_tf(symbol, tfs=["15m","1h","4h","1d"]): ...
    def fetch_orderbook(symbol, depth=20): ...
    def fetch_funding_rate(symbol): ...
```

**注意點**:
- 處理 WebSocket 斷線重連
- K 線「尚未收盤」的標記要傳出去(避免用未完成 K 線做訊號)
- 時間戳全部用 UTC

### 4.2 L2 指標引擎

**職責**:多時間框架的指標計算

**技術選擇**:
- `ta-lib`(C 實作,快)或 `pandas-ta`(純 Python,易裝)

**核心介面**:
```python
def compute_indicators(ohlcv_multi_tf: dict) -> dict:
    """
    輸入: {"1h": [[ts,o,h,l,c,v], ...], ...}
    輸出: {"1h": {"rsi": 68, "atr": 420, ...}, ...}
    """
```

**最少要有**:RSI、ATR、MACD、Bollinger Bands、Volume MA

**進階(後期加)**:OBV、Stochastic、Ichimoku、VWAP

### 4.3 L3 訂單模擬引擎

**職責**:模擬下單,**真實到能反映滑點**

**滑點模擬(critical)**:
```python
def simulate_fill(price, side, size, orderbook):
    """
    根據訂單簿深度模擬實際成交價
    - 小單 (size < 0.5% of depth): slippage ≈ 0.05%
    - 中單 (0.5%-2%): 線性吃深度
    - 大單 (>2%): 警告 + 加重滑點
    """
```

**手續費**:Binance 永續 taker 0.05%、maker 0.02%——預設 taker

**訂單類型**:
- market、limit、stop_market、stop_limit、take_profit
- 觸發後進入「即時撮合佇列」,下一個 tick 才成交(避免 hindsight bias)

### 4.4 L4 持倉管理

**職責**:追蹤多空持倉、計算已實現 + 未實現盈虧

**注意**:
- 同一 symbol 可同時持多空(對沖模式)還是只能擇一(單向模式)?
- **MVP 用單向模式**(更接近散戶實況)
- 部分平倉支援(`size_partial`)

### 4.5 L5 反饋層

**核心指標(必須)**:
- 累計 P&L(USDT 與 R)
- 勝率、平均盈虧比
- 最大回撤(Max Drawdown)
- 連續虧損次數
- 夏普值(Sharpe,週度更新)

**呈現**:儀表板首頁,即時更新

---

## 5. L6 Learning Engine

### 5.1 核心職責

**把主觀判斷變成結構化資料,讓「為什麼」可以被統計。**

### 5.2 完整決策的 5 階段

平庸平台只記 2 個(Entry + Exit)。本平台記 5 個:

1. **Pre-trade**:下單前的 market_snapshot + 你的預測 + 信心
2. **Entry**:成交價、滑點、實際成本
3. **In-trade**:持倉期間是否改變想法、情緒變化(可選)
4. **Exit**:出場價 + exit_reason
5. **Post-trade**:24h 後走勢 + MFE/MAE + prediction_correct

學習價值最高的是 **1 跟 5**。

### 5.3 24h 自動回填

```python
def reconcile():
    """每小時觸發,找超過 24h 的 record,回填 outcome"""
    for r in pending_records():
        if hours_since(r.ts) >= 24:
            close_24h = fetch_close_24h_after(r.ts)
            entry = r.action["entry"]

            # 算 R
            sl_distance = abs(entry - r.action["sl"])
            move = (close_24h - entry) if r.action["side"] == "long" else (entry - close_24h)
            pnl_R = move / sl_distance

            r.post_outcome = {
                "price_after_24h": close_24h,
                "pct_change": (close_24h - entry) / entry,
                "pnl_R": pnl_R,
                "prediction_correct": direction_matches(r, close_24h),
                "exit_reason": detect_exit_reason(r, close_24h)
            }
            r.is_locked = True
            save(r)
```

### 5.4 歸因引擎(基本版)

```python
def attribution_by_tag(tag_dimension="setup_type"):
    """
    回答: 「我用 X 標籤的勝率/EV 多少?」
    """
    by_tag = {}
    for r in completed_records():
        tag_value = r.trader_state["reasoning_tags"][tag_dimension]
        by_tag.setdefault(tag_value, []).append(r.post_outcome["pnl_R"])

    return {
        tag: {
            "n": len(rs),
            "win_rate": sum(1 for r in rs if r > 0) / len(rs),
            "avg_R": sum(rs) / len(rs),
            "EV_R": sum(rs) / len(rs),  # = avg_R when normalized
            "warning": "n<20" if len(rs) < 20 else None
        } for tag, rs in by_tag.items()
    }
```

### 5.5 多維交叉歸因

```python
def attribution_cross(dim_a="setup_type", dim_b="market_regime"):
    """
    回答: 「我做 X setup 在 Y regime 表現如何?」
    這就是歸因報表 v1
    """
    # 笛卡爾積,計算每格的 n / win_rate / EV
```

---

## 6. L7 Discovery Engine

### 6.1 核心理念

**Tier 1-3 是你查資料,Tier 4 是資料找你。**

### 6.2 三大子模組

#### 6.2.1 Hidden Correlation Scanner

**演算法**:
```
for each pair (label_A_value, label_B_value):
    samples = filter(decisions, has both labels)
    if len(samples) < 20: skip
    win_rate_subset = mean(win_rate of samples)
    win_rate_baseline = mean(win_rate of all decisions)
    chi2_p = chi_square_test(samples, all)
    if chi2_p < 0.05:
        record_finding(label_A, label_B, effect_size, p)

# 多重比較校正 (CRITICAL)
findings = bonferroni_correct(findings, alpha=0.05)
# 或用更寬鬆的 FDR (Benjamini-Hochberg)

return findings sorted by effect_size desc
```

**輸出範例**:
> 「過去 60 筆,funding_rate=negative × any_setup → win 71% (n=14) vs base 52%,p=0.003」

#### 6.2.2 Meta-skill Diagnostics

| 元能力 | 計算 | 健康指標 |
|---|---|---|
| 信心校準 | `LinearRegression(confidence, EV)` | slope > 0,R² > 0.3 |
| 情緒影響 | `ANOVA(emotion, EV)` | F p < 0.05 = 情緒影響顯著 |
| 時段適配 | `ANOVA(session, EV)` | 找出 sweet spot |
| 預測對齊 | `prediction_correct % 月對月` | 應遞增 |

每週生成「**元能力雷達圖**」(4 軸打分,0-100)。

#### 6.2.3 Regime Decay Detector

```python
for each (setup, regime) combo:
    ev_30d = rolling_ev(combo, window=30)
    ev_60d = rolling_ev(combo, window=60)
    ev_90d = rolling_ev(combo, window=90)

    if ev_30d < ev_90d * 0.5 and abs(ev_90d) > 0.2:
        alert(f"{setup} @ {regime} 衰退中: 90d {ev_90d}R, 30d {ev_30d}R")
```

### 6.3 Killer Feature: Suggested Experiments

L7 不只報告,**主動提假設讓你驗證**。

每週 Discovery Report 結尾自動生成:

```
[下週建議實驗]
假設: 你在 funding_rate < -0.01% 時做得好
實驗: 接下來一週,刻意在此條件下執行 5 筆 mean_reversion 多單
預期樣本: 5 筆 (已在過去歷史中累積 14 筆)
驗證後將自動更新 discovery_log
```

寫入 `experiments` 表,等待你執行,完成後系統自動評估。

### 6.4 觸發機制

| 時機 | 動作 |
|---|---|
| 每筆新單後 | 微更新該標籤累計統計 |
| 每週日 08:00 | 完整掃描,生成 Discovery Report |
| 即時 | 模式 p 值首次 < 0.05 → 推播提示 |

### 6.5 Discovery 自我評估

L7 自己也會 overfit。所以 `discovery_log` 表會追蹤:
- 每個 discovery 後續是否真的成立
- L7 的「準確率」自己也是個指標
- 若 L7 的 hit_rate < 50%,自動降低提醒頻率

**這是 meta-meta-learning。**

---

## 7. 歸因問題清單(平台要能回答的 7 個答案)

| # | 類型 | 問題 |
|---|---|---|
| A | self-knowledge | 我在 confidence_5 時 EV 真的比 confidence_2 高嗎? |
| B | strategy × context | mean_reversion 在 ranging 賺、在 trending 虧? |
| C | recurring failures | 我虧 >2R 的單,有沒有共同標籤? |
| D | risk profile | 我設 1R 停損的被打率 vs 1.5R 的差異? |
| E | prediction skill | 我的 prediction_correct 月對月是否遞增? |
| **6** | **active discovery** | **系統能告訴我,我有哪些自己沒意識到的勝率關聯?** |
| **7** | **meta-skill** | **系統能診斷我的元能力(信心校準、時段適配、setup 衰退)?** |

A-E 是 L6 能回答的(被動)。
6-7 是 L7 才能回答的(主動)——**這是「比一般強大」的核心**。

---

## 8. 反饋迴路全景

```
┌──────────────┐
│ 你 9-11am    │
│ 觀察 + 預測   │
└──────┬───────┘
       │ 形成 prediction_text + reasoning_tags
       ▼
┌──────────────┐
│ 下單(模擬)  │ ← 強制填寫 6 維標籤 + R-multiple
└──────┬───────┘
       │ 寫入 decisions 表,立即鎖定
       ▼
┌──────────────┐
│ 24h 後系統   │
│ 自動回填     │ ← reconcile() 每小時跑
│ post_outcome │
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ L6 歸因      │ ← 你查資料: 「我做 X 的勝率?」
│ (passive)    │
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ L7 Discovery │ ← 資料找你: 「你沒注意到 Y 模式」
│ (active)     │
└──────┬───────┘
       │ 提出假設 → experiments 表
       ▼
┌──────────────┐
│ Suggested    │
│ Experiment   │
│ (下週實驗)   │
└──────┬───────┘
       │
       └─→ 回到頂端: 你下週的「9-11am 觀察」帶著假設去驗證
```

**5 個循環後,你會比 95% 的散戶更懂自己。**

---

## 9. 反模式檢查清單

### 9.1 「壞標籤」5 問

打完標籤,對自己這樣問:

1. ❓ 一週後我看這個標籤,**能否回想當時市場狀態**?(不能 = 太模糊)
2. ❓ 兩種完全不同情境會打**同樣的標籤**?(會 = 區分度不夠)
3. ❓ 同樣情境,我有時打 A 有時打 B?(是 = 沒互斥)
4. ❓ 這個標籤是**虧錢後才想到的**?(是 = 違反鎖定)
5. ❓ 標籤裡藏了「結果預測」?(有 = 重疊問題,統計失效)

任一題 yes → 該標籤重設計。

### 9.2 系統反模式

- ❌ 給自己「補登」的後門(讓事後改 reasoning_tags)
- ❌ 用 % return 而非 R-multiple 統計
- ❌ 樣本 n < 20 還顯示「勝率 X%」(必須打灰或標警告)
- ❌ Discovery 不做多重比較校正(會跑出一堆假陽性)
- ❌ 標籤太細(每維度 > 10 個 → 樣本永遠不夠)

---

## 10. 演進路徑(3 個月計畫)

### 10.1 第 1 月:MVP + 日常化

- 跑通 L1-L6 簡化版(~250 行 Python)
- 每天 9-11am 做 1-3 筆模擬下單,**全部填好標籤**
- 累積 30+ 筆 decisions
- 月底:第一次手動歸因,看哪些標籤最常用、哪些從沒用

### 10.2 第 2 月:標籤迭代 + L7 上線

- 根據第 1 月樣本,把高頻標籤拆細、低頻合併
- 上線 L7 三個子模組
- 開始接收 Suggested Experiments,每週驗證 1 個
- 累計 80+ 筆 decisions

### 10.3 第 3 月:meta 能力 + 體系穩定

- Discovery_log 已累積 10+ 個 finding,可評估 L7 自身準確率
- 元能力雷達圖月對月對比
- 標籤體系穩定,基本不再大改
- **這時你已不是 3 月前的你**——你知道自己的盲點、優勢、節奏

### 10.4 第 4 月之後:可選的深化路徑

- 接入即時實盤(從 paper 跨到 real,但保留同樣的 DecisionRecord 結構)
- 整合多 symbol(從 BTC 拓展到 ETH、SOL 等)
- 建社群版(分享匿名化的 discovery 模式給其他人)

---

## 附錄 A:技術棧建議

| 層級 | 技術 | 理由 |
|---|---|---|
| 後端 | Python 3.11+ | 量化生態最完整 |
| 即時資料 | `ccxt.pro` | 多交易所統一介面 |
| 指標 | `pandas-ta` 或 `ta-lib` | 廣泛測試 |
| 統計 | `scipy.stats`、`statsmodels` | L7 必備 |
| 資料庫 | SQLite (MVP) → PostgreSQL (規模化) | 簡單先行 |
| 排程 | `APScheduler` | reconcile + Discovery 定時跑 |
| 前端(MVP) | Streamlit | 3 天能跑出儀表板 |
| 前端(進階) | Next.js + Recharts | 彈性與美觀 |

---

## 附錄 B:檢查清單(動工前)

實作前,確認以下都答得出來:

- [ ] 我能畫出 7 層架構圖,不查資料
- [ ] 我知道為什麼 R-multiple 比 % return 重要
- [ ] 我能列出 6 維標籤,並解釋為什麼分這 6 維
- [ ] 我知道為什麼 outcome 必須由系統自動回填
- [ ] 我能解釋什麼是 Bonferroni 校正,為什麼 L7 需要它
- [ ] 我知道前 3 週的歸因報表為什麼沒太大價值(樣本不足)
- [ ] 我能說出 Suggested Experiments 為什麼是 killer feature
- [ ] 我有能力延後「小功能加一加」的衝動,直到 MVP 跑滿 30 筆

任一 ❌ → 回頭重讀對應章節再動工。

---

## 附錄 C:名詞表

| 名詞 | 定義 |
|---|---|
| DecisionRecord | 每筆下單對應的完整資料結構,平台心臟 |
| R-multiple | 用 1R(風險單位)為單位記錄盈虧,跨 setup 可比 |
| MFE/MAE | Maximum Favorable/Adverse Excursion,持倉期間最有利/最不利點位 |
| Tier 4 | 系統主動發現你沒問的問題的能力層級 |
| Bonferroni 校正 | 多重比較校正,避免假陽性 |
| Discovery Engine (L7) | 主動掃描標籤組合、診斷元能力、警告策略衰退 |
| Suggested Experiment | L7 提出的假設,等待你驗證 |
| Decision Attribution | 把每次下單拆解到「哪些因素貢獻了結果」的分析 |

---

## 結語

這份規格的價值不在於「文件本身」,而在於它**強迫你在動工前想清楚每個設計選擇的代價**。

當你 3 個月後想加一個新功能時,先問:
1. 它屬於哪一層?
2. 它會反推改動哪幾個資料表?
3. 它會逼出新的標籤維度嗎?
4. 它讓平台從「Tier X」進到「Tier X+1」嗎?

**功能加得快不是強大,知道為什麼不加哪些功能才是強大**。

---

*本文件由 6 輪 Socratic 對話蒸餾而成。每個設計選擇都對應一個你親自做過的決定。三個月後讀,如果有些選擇看起來「為什麼當初要這樣」——回到對話原稿,你會看見當時的取捨。*
