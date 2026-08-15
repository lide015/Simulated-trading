"""WP1 每日盤後批次抓取的協調器(orchestrator)。

依報告「資料品質與監控」原則:
- 冪等:每個 dataset 用 (日期＋資料集) 當 fetch_log 的 key,upsert 到事實表
  用 (日期＋股號) 當 key,重跑不會重複。
- 單一資料源失敗不能拖垮整批:每個 dataset 各自 try/except,失敗記
  fetch_log 並繼續下一個。
- 缺漏可回補:所有結果都寫 fetch_log,配合 `storage.db.missing_fetch_dates`
  之後可以補跑。
"""
from __future__ import annotations

import datetime as dt
import logging

import duckdb

from taiwan_stock_ai.data import twse_client
from taiwan_stock_ai.storage.db import get_connection, log_fetch_result, upsert_rows

logger = logging.getLogger(__name__)


def _run_dataset(
    conn: duckdb.DuckDBPyConnection,
    *,
    dataset: str,
    table: str,
    key_columns: list[str],
    fetch_date: dt.date,
    fetch_fn,
) -> int:
    started_at = dt.datetime.now(dt.timezone.utc)
    try:
        rows = fetch_fn()
    except Exception as exc:  # noqa: BLE001 - 單一資料源失敗要降級,不能整批掛掉
        logger.exception("dataset=%s fetch failed", dataset)
        log_fetch_result(
            conn,
            dataset=dataset,
            fetch_date=fetch_date,
            status="failed",
            error_message=str(exc),
            started_at=started_at,
        )
        return 0

    if rows is None:
        # None 代表「明確知道抓取失敗」(例如處置股端點回傳不明格式),
        # 跟「成功但今天剛好 0 筆」要分開處理。
        log_fetch_result(
            conn,
            dataset=dataset,
            fetch_date=fetch_date,
            status="failed",
            error_message="fetch function returned None (see logs)",
            started_at=started_at,
        )
        return 0

    n = upsert_rows(conn, table, rows, key_columns=key_columns)
    log_fetch_result(
        conn,
        dataset=dataset,
        fetch_date=fetch_date,
        status="success" if n > 0 or rows == [] else "partial",
        row_count=n,
        started_at=started_at,
    )
    return n


def run_daily_fetch(fetch_date: dt.date | None = None, db_path: str | None = None) -> dict[str, int]:
    """跑一次完整的盤後批次抓取,回傳每個 dataset 的寫入筆數。"""
    fetch_date = fetch_date or dt.date.today()
    conn = get_connection(db_path)
    results: dict[str, int] = {}

    try:
        results["daily_quotes_twse"] = _run_dataset(
            conn,
            dataset="daily_quotes_twse",
            table="daily_quotes",
            key_columns=["trade_date", "stock_id"],
            fetch_date=fetch_date,
            fetch_fn=lambda: twse_client.fetch_daily_quotes_all(fetch_date),
        )
        results["institutional_trading"] = _run_dataset(
            conn,
            dataset="institutional_trading",
            table="institutional_trading",
            key_columns=["trade_date", "stock_id"],
            fetch_date=fetch_date,
            fetch_fn=lambda: twse_client.fetch_institutional_trading(fetch_date),
        )
        results["monthly_revenue"] = _run_dataset(
            conn,
            dataset="monthly_revenue",
            table="monthly_revenue",
            key_columns=["revenue_year_month", "stock_id"],
            fetch_date=fetch_date,
            fetch_fn=twse_client.fetch_monthly_revenue,
        )
        results["material_news"] = _run_dataset(
            conn,
            dataset="material_news",
            table="material_news",
            key_columns=["announce_date", "stock_id", "seq_no"],
            fetch_date=fetch_date,
            fetch_fn=twse_client.fetch_material_news,
        )
        results["disposition_stocks"] = _run_dataset(
            conn,
            dataset="disposition_stocks",
            table="disposition_stocks",
            key_columns=["stock_id", "start_date"],
            fetch_date=fetch_date,
            fetch_fn=twse_client.fetch_disposition_stocks,
        )
    finally:
        conn.close()

    logger.info("daily fetch %s done: %s", fetch_date, results)
    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_daily_fetch()
