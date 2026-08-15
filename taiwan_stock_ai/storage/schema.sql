-- WP3 事實表(DuckDB)。所有表都以「日期＋股號＋資料集」風格的複合主鍵做
-- upsert 冪等鍵,重跑批次不會重複、也不會遺漏(依報告「資料品質與監控」)。

CREATE TABLE IF NOT EXISTS daily_quotes (
    trade_date DATE NOT NULL,
    stock_id VARCHAR NOT NULL,
    stock_name VARCHAR,
    market VARCHAR NOT NULL,        -- 'TWSE' | 'TPEx'
    open DOUBLE,
    high DOUBLE,
    low DOUBLE,
    close DOUBLE,
    volume_shares BIGINT,
    value_twd BIGINT,
    change DOUBLE,
    transaction_count BIGINT,
    fetched_at TIMESTAMP NOT NULL,
    source VARCHAR NOT NULL,
    PRIMARY KEY (trade_date, stock_id)
);

CREATE TABLE IF NOT EXISTS institutional_trading (
    trade_date DATE NOT NULL,
    stock_id VARCHAR NOT NULL,
    foreign_net BIGINT,             -- 外資買賣超(股)
    investment_trust_net BIGINT,    -- 投信買賣超(股)
    dealer_net BIGINT,              -- 自營商買賣超(股)
    total_net BIGINT,               -- 三大法人合計買賣超(股)
    fetched_at TIMESTAMP NOT NULL,
    source VARCHAR NOT NULL,
    PRIMARY KEY (trade_date, stock_id)
);

CREATE TABLE IF NOT EXISTS monthly_revenue (
    revenue_year_month VARCHAR NOT NULL,  -- 'YYYY-MM' 西元年月
    stock_id VARCHAR NOT NULL,
    company_name VARCHAR,
    revenue BIGINT,
    revenue_last_month BIGINT,
    revenue_last_year BIGINT,
    mom_pct DOUBLE,
    yoy_pct DOUBLE,
    fetched_at TIMESTAMP NOT NULL,
    source VARCHAR NOT NULL,
    PRIMARY KEY (revenue_year_month, stock_id)
);

-- 重大訊息:依報告合規建議,只存標題/連結/時間戳,不存全文。
CREATE TABLE IF NOT EXISTS material_news (
    announce_date DATE NOT NULL,
    stock_id VARCHAR NOT NULL,
    seq_no VARCHAR NOT NULL,        -- 來源序號,查無則用內容 hash 避免重複
    title VARCHAR,
    url VARCHAR,
    fetched_at TIMESTAMP NOT NULL,
    source VARCHAR NOT NULL,
    PRIMARY KEY (announce_date, stock_id, seq_no)
);

-- 處置股清單:訊號引擎必須排除,不可對處置股產生當沖訊號。
CREATE TABLE IF NOT EXISTS disposition_stocks (
    stock_id VARCHAR NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE,
    reason VARCHAR,
    fetched_at TIMESTAMP NOT NULL,
    source VARCHAR NOT NULL,
    PRIMARY KEY (stock_id, start_date)
);

-- 模組三:本地訊號引擎輸出(0 token,規則計算)。
CREATE TABLE IF NOT EXISTS signals (
    signal_date DATE NOT NULL,
    stock_id VARCHAR NOT NULL,
    signal_name VARCHAR NOT NULL,   -- 'momentum' | 'ma_breakout'
    tag VARCHAR NOT NULL,           -- '當沖' | '波段' | '中長線'
    direction VARCHAR NOT NULL,     -- 'bullish' | 'bearish'
    strength DOUBLE,
    description VARCHAR,
    excluded_reason VARCHAR,        -- 例如 '處置股',非 NULL 代表不應推播當沖
    computed_at TIMESTAMP NOT NULL,
    PRIMARY KEY (signal_date, stock_id, signal_name)
);

-- 抓取水位/告警記錄,對應報告「冪等性、失敗告警、缺漏補抓」。
CREATE TABLE IF NOT EXISTS fetch_log (
    dataset VARCHAR NOT NULL,
    fetch_date DATE NOT NULL,
    status VARCHAR NOT NULL,        -- 'success' | 'partial' | 'failed'
    row_count BIGINT,
    error_message VARCHAR,
    started_at TIMESTAMP NOT NULL,
    finished_at TIMESTAMP,
    PRIMARY KEY (dataset, fetch_date)
);
