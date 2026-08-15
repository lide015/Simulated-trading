"""FinMind API client — 備援資料源(不是主資料源)。

來源:https://finmindtrade.com/,官方 quickstart 說明免費額度為
300 次/小時,註冊並驗證信箱後帶 token 呼叫可提高到 600 次/小時。這裡的
`RateLimiter` 保守設一個略低於官方上限的值,避免踩線。

用途:官方 TWSE/TPEx OpenAPI 打不到、或需要「歷史區間」查詢(官方端點多
半只回最新快照)時的備援與交叉驗證,**不要當唯一來源**(報告 Key
Findings #5 / 資料源章節)。
"""
from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from taiwan_stock_ai.config import settings
from taiwan_stock_ai.data.http import RateLimiter, get_json
from taiwan_stock_ai.data.util import to_float, to_int

logger = logging.getLogger(__name__)

BASE_URL = "https://api.finmindtrade.com/api/v4/data"

# 保守值:有 token 時官方上限 600/hr,沒 token 是 300/hr。這裡用比較低的
# 500/hr 當預設,留緩衝給同一小時內其他呼叫者(如手動除錯)。
_rate_limiter = RateLimiter(
    max_calls=min(settings.finmind_hourly_limit, 500), period_seconds=3600
)


def _fetch_dataset(dataset: str, *, data_id: str | None = None, start_date: str, end_date: str | None = None) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"dataset": dataset, "start_date": start_date}
    if data_id:
        params["data_id"] = data_id
    if end_date:
        params["end_date"] = end_date
    if settings.finmind_token:
        params["token"] = settings.finmind_token

    payload = get_json(BASE_URL, params=params, rate_limiter=_rate_limiter)
    if not isinstance(payload, dict) or payload.get("status") != 200:
        logger.warning("FinMind dataset=%s unexpected response: %r", dataset, payload)
        return []
    return payload.get("data", [])


def fetch_stock_price(stock_id: str, start_date: dt.date, end_date: dt.date | None = None) -> list[dict[str, Any]]:
    """備援日 K 資料(dataset=TaiwanStockPrice)。"""
    raw = _fetch_dataset(
        "TaiwanStockPrice",
        data_id=stock_id,
        start_date=start_date.isoformat(),
        end_date=(end_date or dt.date.today()).isoformat(),
    )
    now = dt.datetime.now(dt.timezone.utc)
    rows: list[dict[str, Any]] = []
    for item in raw:
        trade_date_raw = item.get("date")
        if not trade_date_raw:
            continue
        rows.append(
            {
                "trade_date": dt.date.fromisoformat(trade_date_raw),
                "stock_id": item.get("stock_id", stock_id),
                "stock_name": None,
                "market": "TWSE/TPEx",  # FinMind 未在此 dataset 區分市場別
                "open": to_float(item.get("open")),
                "high": to_float(item.get("max")),
                "low": to_float(item.get("min")),
                "close": to_float(item.get("close")),
                "volume_shares": to_int(item.get("Trading_Volume")),
                "value_twd": to_int(item.get("Trading_money")),
                "change": to_float(item.get("spread")),
                "transaction_count": to_int(item.get("Trading_turnover")),
                "fetched_at": now,
                "source": "finmind:TaiwanStockPrice",
            }
        )
    return rows


def fetch_institutional_investors(stock_id: str, start_date: dt.date) -> list[dict[str, Any]]:
    """備援三大法人買賣超(dataset=TaiwanStockInstitutionalInvestorsBuySell)。"""
    raw = _fetch_dataset(
        "TaiwanStockInstitutionalInvestorsBuySell",
        data_id=stock_id,
        start_date=start_date.isoformat(),
    )
    now = dt.datetime.now(dt.timezone.utc)
    by_date: dict[str, dict[str, Any]] = {}
    for item in raw:
        date = item.get("date")
        name = (item.get("name") or "").lower()
        buy = to_int(item.get("buy")) or 0
        sell = to_int(item.get("sell")) or 0
        net = buy - sell
        bucket = by_date.setdefault(
            date,
            {
                "trade_date": dt.date.fromisoformat(date) if date else None,
                "stock_id": stock_id,
                "foreign_net": 0,
                "investment_trust_net": 0,
                "dealer_net": 0,
                "total_net": 0,
                "fetched_at": now,
                "source": "finmind:TaiwanStockInstitutionalInvestorsBuySell",
            },
        )
        if "foreign" in name:
            bucket["foreign_net"] += net
        elif "trust" in name:
            bucket["investment_trust_net"] += net
        elif "dealer" in name:
            bucket["dealer_net"] += net
        bucket["total_net"] += net

    return [row for row in by_date.values() if row["trade_date"] is not None]
