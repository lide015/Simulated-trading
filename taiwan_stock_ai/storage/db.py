"""DuckDB 連線與 upsert 輔助函式。

MVP 選擇 DuckDB(單檔、免服務、欄式分析快)取代原報告建議延續的 Supabase
——因為這個 repo 目前沒有任何既有 Supabase 專案可以延續。upsert 介面刻意
寫成表格無關的通用函式,未來要換成 Postgres/Supabase 時只需要換掉這個
模組內部實作,呼叫端(data/signals/notify)完全不用改。
"""
from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path
from typing import Any, Iterable

import duckdb

from taiwan_stock_ai.config import settings

logger = logging.getLogger(__name__)

_SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def get_connection(db_path: str | None = None) -> duckdb.DuckDBPyConnection:
    """開啟(或建立)DuckDB 資料庫並確保 schema 存在。"""
    path = db_path or settings.duckdb_path
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(path)
    conn.execute(_SCHEMA_PATH.read_text(encoding="utf-8"))
    return conn


def upsert_rows(
    conn: duckdb.DuckDBPyConnection,
    table: str,
    rows: list[dict[str, Any]],
    key_columns: Iterable[str],
) -> int:
    """把一批 dict 記錄 upsert 進指定表格。

    以 key_columns 做 ON CONFLICT 判斷,同一(日期＋股號＋資料集)重跑批次
    只會覆蓋、不會重複——這是報告點名的「冪等性」要求。

    回傳實際寫入的筆數(0 代表沒東西可寫,呼叫端可以拿來判斷資料源是否
    今天沒開盤/沒資料)。
    """
    if not rows:
        return 0

    columns = list(rows[0].keys())
    key_columns = list(key_columns)
    update_columns = [c for c in columns if c not in key_columns]

    placeholders = ", ".join(["?"] * len(columns))
    col_list = ", ".join(columns)
    key_list = ", ".join(key_columns)

    if update_columns:
        set_clause = ", ".join(f"{c} = excluded.{c}" for c in update_columns)
        conflict_clause = f"ON CONFLICT ({key_list}) DO UPDATE SET {set_clause}"
    else:
        # 表格的每一欄都是 key(理論上不會發生,但保守處理避免空 SET)
        conflict_clause = f"ON CONFLICT ({key_list}) DO NOTHING"

    sql = f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) {conflict_clause}"

    values = [[row[c] for c in columns] for row in rows]
    conn.executemany(sql, values)
    return len(rows)


def log_fetch_result(
    conn: duckdb.DuckDBPyConnection,
    *,
    dataset: str,
    fetch_date: dt.date,
    status: str,
    row_count: int = 0,
    error_message: str | None = None,
    started_at: dt.datetime | None = None,
) -> None:
    """記錄一次抓取結果,供告警與高水位回補使用。"""
    started_at = started_at or dt.datetime.now(dt.timezone.utc)
    row = {
        "dataset": dataset,
        "fetch_date": fetch_date,
        "status": status,
        "row_count": row_count,
        "error_message": error_message,
        "started_at": started_at,
        "finished_at": dt.datetime.now(dt.timezone.utc),
    }
    upsert_rows(conn, "fetch_log", [row], key_columns=["dataset", "fetch_date"])
    if status != "success":
        logger.warning("fetch %s on %s status=%s error=%s", dataset, fetch_date, status, error_message)


def missing_fetch_dates(
    conn: duckdb.DuckDBPyConnection,
    *,
    dataset: str,
    candidate_dates: Iterable[dt.date],
) -> list[dt.date]:
    """回補缺漏用:給一串候選交易日,回傳哪些日期還沒有成功抓取紀錄。"""
    candidates = list(candidate_dates)
    if not candidates:
        return []
    done = conn.execute(
        "SELECT fetch_date FROM fetch_log WHERE dataset = ? AND status = 'success'",
        [dataset],
    ).fetchall()
    done_dates = {row[0] for row in done}
    return [d for d in candidates if d not in done_dates]
