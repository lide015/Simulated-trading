-- SQLite schema for the DecisionRecord platform (README.md 3.4 三張資料表)。
-- 由 scripts/decision_writer.py 在啟動時自動執行(CREATE TABLE IF NOT EXISTS),
-- 這份檔案本身也是文件:想知道欄位長怎樣,看這裡就夠了。

-- 主表:每筆下單一筆
CREATE TABLE IF NOT EXISTS decisions (
  id TEXT PRIMARY KEY,
  ts TEXT NOT NULL,
  market_snapshot TEXT,            -- JSON(SQLite 無原生 JSON 型別,存 TEXT)
  trader_state TEXT,               -- JSON
  action TEXT,                     -- JSON
  post_outcome TEXT,               -- JSON,24h 後填,在此之前為 NULL
  is_locked BOOLEAN DEFAULT 1      -- 鎖定,不可改(見 README.md 9.2 反模式)
);

CREATE INDEX IF NOT EXISTS idx_ts ON decisions(ts);
CREATE INDEX IF NOT EXISTS idx_setup ON decisions(json_extract(trader_state, '$.reasoning_tags.setup_type'));
CREATE INDEX IF NOT EXISTS idx_regime ON decisions(json_extract(trader_state, '$.reasoning_tags.market_regime'));

-- 實驗表:L7 提的假設 + 你的驗證結果(L7 尚未實作,先備好表格)
CREATE TABLE IF NOT EXISTS experiments (
  id TEXT PRIMARY KEY,
  proposed_at TEXT,
  hypothesis TEXT,            -- 假設文字
  conditions TEXT,            -- JSON,觸發條件 (如: funding < 0)
  target_n INTEGER,           -- 需要幾筆樣本
  status TEXT,                -- proposed | active | concluded
  conclusion TEXT,            -- 驗證結果
  related_decision_ids TEXT   -- JSON,涉及的下單 id 清單
);

-- Discovery 自身 log:防止 L7 自己 overfit(L7 尚未實作,先備好表格)
CREATE TABLE IF NOT EXISTS discovery_log (
  id TEXT PRIMARY KEY,
  detected_at TEXT,
  type TEXT,                  -- correlation | meta_skill | decay
  pattern_description TEXT,
  p_value REAL,
  effect_size REAL,
  n_samples INTEGER,
  hit_or_miss BOOLEAN         -- 後續驗證,該 pattern 是否真的成立
);
