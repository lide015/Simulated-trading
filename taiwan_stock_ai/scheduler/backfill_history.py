"""補歷史資料。

官方 TWSE OpenAPI 的每日快照端點(`STOCK_DAY_ALL`)沒有歷史查詢參數,只能
靠排程每天累積一天——照那個節奏,K 線圖要好幾個月才會有像樣的長度。
FinMind(備援資料源)的 `TaiwanStockPrice` dataset 支援真正的日期區間查詢,
可以一次把過去 N 天補回來。

依報告「資料源」章節的定調,FinMind 是備援/交叉驗證來源,不是主資料源,
所以這支程式**只在明確手動執行時**跑(CLI 或 GitHub Actions
workflow_dispatch),不是每日排程的一部分,也不取代 `twse_client` 當每日
主要資料來源——`scheduler/run_daily.py` 完全沒有變動。

用法:
    # 自動選今天成交值最高的 30 檔,補過去 90 天
    python -m taiwan_stock_ai.scheduler.backfill_history

    # 指定股票代號、天數
    python -m taiwan_stock_ai.scheduler.backfill_history --stock-ids 2330,2454 --days 180
"""
from __future__ import annotations

import argparse
import datetime as dt
import logging
import sys
from typing import Optional

import duckdb

from taiwan_stock_ai.data import finmind_client
from taiwan_stock_ai.storage.db import get_connection, upsert_rows

logger = logging.getLogger(__name__)


def pick_top_stock_ids(conn: duckdb.DuckDBPyConnection, limit: int) -> list[str]:
    """沒指定 --stock-ids 時,從最新一天的快照挑成交值最高的 N 檔。"""
    rows = conn.execute(
        """
        SELECT stock_id FROM daily_quotes
        WHERE trade_date = (SELECT MAX(trade_date) FROM daily_quotes)
        ORDER BY value_twd DESC NULLS LAST
        LIMIT ?
        """,
        [limit],
    ).fetchall()
    return [r[0] for r in rows]


def _existing_stock_name(conn: duckdb.DuckDBPyConnection, stock_id: str) -> Optional[str]:
    row = conn.execute(
        "SELECT stock_name FROM daily_quotes WHERE stock_id = ? AND stock_name IS NOT NULL LIMIT 1",
        [stock_id],
    ).fetchone()
    return row[0] if row else None


def run_backfill(
    conn: duckdb.DuckDBPyConnection, stock_ids: list[str], days: int
) -> dict[str, int]:
    """對每檔股票呼叫 FinMind、upsert 進 daily_quotes。回傳 {股票代號: 寫入筆數}。"""
    start_date = dt.date.today() - dt.timedelta(days=days)
    results: dict[str, int] = {}

    for stock_id in stock_ids:
        try:
            rows = finmind_client.fetch_stock_price(stock_id, start_date)
        except Exception:  # noqa: BLE001 - 單一股票失敗不能拖垮整批
            logger.exception("backfill failed for %s", stock_id)
            results[stock_id] = 0
            continue

        # FinMind 的 TaiwanStockPrice 不回公司名稱,盡量沿用事實表裡已知的
        # 名稱(通常是官方 STOCK_DAY_ALL 那筆填的),不要讓補回來的歷史列
        # stock_name 全部是 NULL(dashboard 的股票搜尋下拉選單會不好看)。
        name = _existing_stock_name(conn, stock_id)
        if name:
            for row in rows:
                row["stock_name"] = name

        n = upsert_rows(conn, "daily_quotes", rows, key_columns=["trade_date", "stock_id"])
        results[stock_id] = n
        logger.info("backfilled %s: %d rows", stock_id, n)

    return results


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stock-ids", help="逗號分隔的股票代號,不指定則自動選今天成交值最高的股票"
    )
    parser.add_argument(
        "--limit", type=int, default=30, help="沒指定 --stock-ids 時自動選幾檔(預設 30)"
    )
    parser.add_argument("--days", type=int, default=90, help="往回補幾天(預設 90)")
    args = parser.parse_args(argv)

    conn = get_connection()
    try:
        stock_ids = (
            [s.strip() for s in args.stock_ids.split(",") if s.strip()]
            if args.stock_ids
            else pick_top_stock_ids(conn, args.limit)
        )
        if not stock_ids:
            logger.error("沒有可補的股票代號(事實表可能還沒有任何資料,先跑過一次 run_daily)")
            return 1

        logger.info("backfilling %d stocks, %d days: %s", len(stock_ids), args.days, stock_ids)
        results = run_backfill(conn, stock_ids, args.days)
    finally:
        conn.close()

    total = sum(results.values())
    failed = [sid for sid, n in results.items() if n == 0]
    logger.info("done: %d rows total across %d stocks", total, len(results))
    if failed:
        logger.warning("no rows written for: %s", failed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
