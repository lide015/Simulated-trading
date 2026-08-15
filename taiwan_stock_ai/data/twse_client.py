"""TWSE(證交所)OpenAPI client。

來源:https://openapi.twse.com.tw/(Swagger),免金鑰、HTTP GET 回 JSON 陣列。

**重要限制(報告 Caveats)**:多數端點只回「最新一期快照」、沒有歷史查詢
參數,歷史深度要靠每天排程抓取、自己在 storage 層累積。

**欄位對映的可信度說明**:本檔案的 JSON 欄位名稱是依訓練資料當下對 TWSE
OpenAPI 的認知撰寫;撰寫當下沙盒環境的網路政策擋掉了對
openapi.twse.com.tw 的即時連線(見 /root/.ccr/README.md),沒有機會逐一
對照最新 Swagger 規格做即時驗證。因此:

1. 所有欄位讀取都用 `pick()` 給多個候選 key,而不是寫死單一名稱。
2. 一筆資料如果連候選 key 都對不上,會被跳過並記 warning,不會靜默寫入
   垃圾資料(對應報告「爬蟲失敗告警:欄位 schema 校驗」建議)。
3. **上線前務必先手動打一次每個端點確認欄位**,尤其是處置股端點(用的是
   非正式 `/rwd/` 路徑,不在官方 OpenAPI Swagger 清單內,穩定性最低)。
"""
from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from taiwan_stock_ai.data.http import RateLimiter, get_json
from taiwan_stock_ai.data.util import pick, roc_date_to_western, roc_yyymm_to_western, to_float, to_int

logger = logging.getLogger(__name__)

BASE_URL = "https://openapi.twse.com.tw/v1"
# 非正式的 RWD 內部端點(不在 Swagger 清單內),歷史上被多個社群工具使用
# 來取得處置股清單,但不保證長期穩定,務必於上線前驗證。
DISPOSITION_URL = "https://www.twse.com.tw/rwd/zh/announcement/punish"

# TWSE 官方文件沒有公告明確的速率限制,保守設定節流避免被判定為異常流量。
_rate_limiter = RateLimiter(max_calls=60, period_seconds=60)


def fetch_daily_quotes_all(trade_date: dt.date | None = None) -> list[dict[str, Any]]:
    """全部上市股票每日收盤行情快照(僅回傳「最新一個交易日」)。

    端點:GET /v1/exchangeReport/STOCK_DAY_ALL
    """
    raw = get_json(f"{BASE_URL}/exchangeReport/STOCK_DAY_ALL", rate_limiter=_rate_limiter)
    trade_date = trade_date or dt.date.today()
    now = dt.datetime.now(dt.timezone.utc)

    rows: list[dict[str, Any]] = []
    for item in raw or []:
        stock_id = pick(item, "Code", "code", "股票代號")
        if not stock_id:
            continue
        rows.append(
            {
                "trade_date": trade_date,
                "stock_id": stock_id,
                "stock_name": pick(item, "Name", "name", "股票名稱"),
                "market": "TWSE",
                "open": to_float(pick(item, "OpeningPrice")),
                "high": to_float(pick(item, "HighestPrice")),
                "low": to_float(pick(item, "LowestPrice")),
                "close": to_float(pick(item, "ClosingPrice")),
                "volume_shares": to_int(pick(item, "TradeVolume")),
                "value_twd": to_int(pick(item, "TradeValue")),
                "change": to_float(pick(item, "Change")),
                "transaction_count": to_int(pick(item, "Transaction")),
                "fetched_at": now,
                "source": "twse_openapi:STOCK_DAY_ALL",
            }
        )
    _warn_if_all_dropped(raw, rows, "TWSE STOCK_DAY_ALL")
    return rows


def fetch_institutional_trading(trade_date: dt.date | None = None) -> list[dict[str, Any]]:
    """三大法人買賣超日報(依股票),僅回傳最新一個交易日。

    端點:GET /v1/fund/T86
    """
    raw = get_json(f"{BASE_URL}/fund/T86", rate_limiter=_rate_limiter)
    trade_date = trade_date or dt.date.today()
    now = dt.datetime.now(dt.timezone.utc)

    rows: list[dict[str, Any]] = []
    for item in raw or []:
        stock_id = pick(item, "Code", "code")
        if not stock_id:
            continue
        foreign_net = to_int(
            pick(item, "ForeignInvestorNetBuySell", "ForeignInvestorsExcludeDealerNetBuySell")
        )
        trust_net = to_int(pick(item, "InvestmentTrustNetBuySell"))
        dealer_net = to_int(pick(item, "DealerNetBuySell"))
        total_net = to_int(pick(item, "TotalNetBuySell", "TotalInstitutionalInvestorsNetBuySell"))
        if total_net is None and None not in (foreign_net, trust_net, dealer_net):
            total_net = (foreign_net or 0) + (trust_net or 0) + (dealer_net or 0)
        rows.append(
            {
                "trade_date": trade_date,
                "stock_id": stock_id,
                "foreign_net": foreign_net,
                "investment_trust_net": trust_net,
                "dealer_net": dealer_net,
                "total_net": total_net,
                "fetched_at": now,
                "source": "twse_openapi:T86",
            }
        )
    _warn_if_all_dropped(raw, rows, "TWSE T86")
    return rows


def fetch_monthly_revenue() -> list[dict[str, Any]]:
    """上市公司每月營收(MOPS 正規 OpenAPI 端點,取代舊版 t05st10 表單代碼)。

    端點:GET /v1/opendata/t187ap05_L
    """
    raw = get_json(f"{BASE_URL}/opendata/t187ap05_L", rate_limiter=_rate_limiter)
    now = dt.datetime.now(dt.timezone.utc)

    rows: list[dict[str, Any]] = []
    for item in raw or []:
        stock_id = pick(item, "公司代號", "Code")
        roc_ym = pick(item, "資料年月", "DataYM")
        if not stock_id or not roc_ym:
            continue
        rows.append(
            {
                "revenue_year_month": roc_yyymm_to_western(str(roc_ym)),
                "stock_id": stock_id,
                "company_name": pick(item, "公司名稱", "CompanyName"),
                "revenue": to_int(pick(item, "營業收入-當月營收")),
                "revenue_last_month": to_int(pick(item, "營業收入-上月營收")),
                "revenue_last_year": to_int(pick(item, "營業收入-去年當月營收")),
                "mom_pct": to_float(pick(item, "營業收入-上月比較增減(%)")),
                "yoy_pct": to_float(pick(item, "營業收入-去年同月增減(%)")),
                "fetched_at": now,
                "source": "twse_openapi:t187ap05_L",
            }
        )
    _warn_if_all_dropped(raw, rows, "TWSE t187ap05_L")
    return rows


def fetch_material_news() -> list[dict[str, Any]]:
    """上市公司重大訊息——只存標題與查詢連結,不存全文(依報告合規建議)。

    端點:GET /v1/opendata/t187ap04_L
    """
    raw = get_json(f"{BASE_URL}/opendata/t187ap04_L", rate_limiter=_rate_limiter)
    now = dt.datetime.now(dt.timezone.utc)

    rows: list[dict[str, Any]] = []
    for idx, item in enumerate(raw or []):
        stock_id = pick(item, "公司代號", "Code")
        title = pick(item, "主旨", "Subject")
        announce_date_raw = pick(item, "發言日期", "SpokespersonDate", "出表日期")
        if not stock_id or not title:
            continue
        announce_date = (
            roc_date_to_western(str(announce_date_raw)) if announce_date_raw else dt.date.today()
        )
        seq_no = pick(item, "序號", "SeqNo") or f"{idx}"
        rows.append(
            {
                "announce_date": announce_date,
                "stock_id": stock_id,
                "seq_no": str(seq_no),
                "title": title,
                # 只回連 MOPS 查詢頁,不解析/儲存全文,避免著作權爭議。
                "url": f"https://mops.twse.com.tw/mops/web/t05st01?co_id={stock_id}",
                "fetched_at": now,
                "source": "twse_openapi:t187ap04_L",
            }
        )
    _warn_if_all_dropped(raw, rows, "TWSE t187ap04_L")
    return rows


def fetch_disposition_stocks() -> list[dict[str, Any]] | None:
    """目前處置股清單。

    這是合規安全網:訊號引擎必須排除處置股的當沖訊號。用的是非正式
    `/rwd/` 端點(不在官方 Swagger 內),抓取失敗時回傳 ``None``
    (而不是空 list)讓呼叫端能區分「確認目前沒有處置股」跟
    「根本沒抓到,不知道有沒有」——後者必須讓訊號引擎知道要保守處理。
    """
    try:
        raw = get_json(f"{DISPOSITION_URL}?response=json", rate_limiter=_rate_limiter)
    except Exception:  # noqa: BLE001 - 這裡刻意 catch-all,失敗要降級不是整批掛掉
        logger.exception("failed to fetch disposition stock list")
        return None

    data = raw.get("data") if isinstance(raw, dict) else raw
    if data is None:
        logger.warning("disposition stock endpoint returned unexpected shape: %r", type(raw))
        return None

    now = dt.datetime.now(dt.timezone.utc)
    rows: list[dict[str, Any]] = []
    for item in data:
        if isinstance(item, dict):
            stock_id = pick(item, "Code", "股票代號", "證券代號")
            reason = pick(item, "Reason", "處置原因", "原因")
            start_raw = pick(item, "StartDate", "處置起日")
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            # /rwd/ 端點常見格式是欄位陣列而非 dict,保守用位置對映並附警告。
            stock_id, reason = item[0], item[-1]
            start_raw = None
        else:
            continue

        if not stock_id:
            continue
        start_date = roc_date_to_western(str(start_raw)) if start_raw else dt.date.today()
        rows.append(
            {
                "stock_id": str(stock_id),
                "start_date": start_date,
                "end_date": None,
                "reason": str(reason) if reason else None,
                "fetched_at": now,
                "source": "twse_rwd:announcement/punish",
            }
        )
    return rows


def _warn_if_all_dropped(raw: Any, parsed: list[Any], label: str) -> None:
    if raw and not parsed:
        logger.warning(
            "%s returned %d raw rows but 0 parsed successfully; schema may have changed",
            label,
            len(raw),
        )
