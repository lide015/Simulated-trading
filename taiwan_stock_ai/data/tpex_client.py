"""TPEx(櫃買中心)OpenAPI client — 上櫃股票資料。

來源:https://www.tpex.org.tw/openapi/(Swagger),免金鑰、HTTP GET 回 JSON。

報告明確指出的坑:「上櫃資料獨立一套,欄位命名與上市不一致(上市多中文
欄名、上櫃多英文欄名),跨市場需自建對映表」——這裡的 `_pick()` 候選欄位
就是那張對映表的雛形。

**端點路徑的可信度說明**:跟 `twse_client.py` 一樣,本檔案撰寫當下沙盒的
網路政策擋掉了對 tpex.org.tw 的即時連線,無法對照最新 Swagger 規格逐一
驗證端點路徑與欄位名稱。上線前務必先手動確認
`https://www.tpex.org.tw/openapi/` 的 Swagger 清單,若路徑不同,只要改
`DAILY_QUOTES_URL` 這個常數即可,不影響其他程式碼。
"""
from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from taiwan_stock_ai.data.http import RateLimiter, get_json
from taiwan_stock_ai.data.util import pick, to_float, to_int

logger = logging.getLogger(__name__)

BASE_URL = "https://www.tpex.org.tw/openapi/v1"
DAILY_QUOTES_URL = f"{BASE_URL}/tpex_mainboard_quotes"

_rate_limiter = RateLimiter(max_calls=60, period_seconds=60)


def fetch_daily_quotes_all(trade_date: dt.date | None = None) -> list[dict[str, Any]]:
    """全部上櫃股票每日收盤行情快照(僅回傳最新一個交易日)。"""
    raw = get_json(DAILY_QUOTES_URL, rate_limiter=_rate_limiter)
    trade_date = trade_date or dt.date.today()
    now = dt.datetime.now(dt.timezone.utc)

    rows: list[dict[str, Any]] = []
    for item in raw or []:
        stock_id = pick(item, "Code", "SecuritiesCompanyCode", "代號")
        if not stock_id:
            continue
        rows.append(
            {
                "trade_date": trade_date,
                "stock_id": stock_id,
                "stock_name": pick(item, "Name", "CompanyName", "名稱"),
                "market": "TPEx",
                "open": to_float(pick(item, "Open", "OpeningPrice")),
                "high": to_float(pick(item, "High", "HighestPrice")),
                "low": to_float(pick(item, "Low", "LowestPrice")),
                "close": to_float(pick(item, "Close", "ClosingPrice")),
                "volume_shares": to_int(pick(item, "TradingShares", "Volume", "TradeVolume")),
                "value_twd": to_int(pick(item, "TradingValue", "Amount", "TradeValue")),
                "change": to_float(pick(item, "Change")),
                "transaction_count": to_int(pick(item, "Transaction", "TransactionNumber")),
                "fetched_at": now,
                "source": "tpex_openapi:tpex_mainboard_quotes",
            }
        )
    if raw and not rows:
        logger.warning(
            "TPEx daily quotes returned %d raw rows but 0 parsed; schema/endpoint may be wrong",
            len(raw),
        )
    return rows
