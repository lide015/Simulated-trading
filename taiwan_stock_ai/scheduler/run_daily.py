"""每日盤後批次的單一進入點:WP1 抓取 → WP3 落地 → 模組三訊號引擎。

本地開發可以直接 `python -m taiwan_stock_ai.scheduler.run_daily` 執行;
正式環境由 `.github/workflows/taiwan_stock_daily_fetch.yml` 的 cron 呼叫
(對應報告「免費雲端無伺服器:GitHub Actions」建議)。
"""
from __future__ import annotations

import datetime as dt
import logging
import sys

from taiwan_stock_ai.data.fetch_daily import run_daily_fetch
from taiwan_stock_ai.signals.engine import run_signal_engine
from taiwan_stock_ai.storage.db import get_connection

logger = logging.getLogger(__name__)


def main(fetch_date: dt.date | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    fetch_date = fetch_date or dt.date.today()

    if fetch_date.weekday() >= 5:
        # 台股週末不開盤;官方快照端點只回「最新一期」,若照樣抓會把上個
        # 交易日的資料誤標成今天的日期,汙染事實表,所以週末直接跳過。
        # 已知限制:國定假日 cron 仍不知道,需要之後補交易日曆判斷
        # (見 docs/taiwan-stock-ai-blueprint.md 的「Caveats」)。
        logger.info("%s is a weekend, skipping (TWSE does not trade)", fetch_date)
        return 0

    logger.info("=== daily fetch start: %s ===", fetch_date)
    fetch_results = run_daily_fetch(fetch_date)
    logger.info("fetch results: %s", fetch_results)

    conn = get_connection()
    try:
        n_signals = run_signal_engine(conn, fetch_date)
    finally:
        conn.close()
    logger.info("=== daily fetch done: %s, %d signals ===", fetch_date, n_signals)
    return 0


if __name__ == "__main__":
    sys.exit(main())
