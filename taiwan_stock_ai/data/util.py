"""跨 client 共用的小工具:欄位對映、型別轉換、民國曆轉換。"""
from __future__ import annotations

import datetime as dt
from typing import Any


def pick(row: dict[str, Any], *keys: str, default: Any = None) -> Any:
    """依序嘗試多個候選欄位名稱,回傳第一個有值的。

    官方 API 的欄位名稱偶爾會變(報告 Caveats 明確提到這點),用候選清單
    而非寫死單一 key,可以在欄位改名時多撐一下,並方便之後補上新別名。
    """
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return row[key]
    return default


def to_float(val: Any) -> float | None:
    if val in (None, "", "--", "N/A"):
        return None
    try:
        return float(str(val).replace(",", ""))
    except ValueError:
        return None


def to_int(val: Any) -> int | None:
    f = to_float(val)
    return int(f) if f is not None else None


def roc_yyymm_to_western(roc_ym: str) -> str:
    """民國年月字串(如 '11507')轉西元 'YYYY-MM'。"""
    roc_ym = roc_ym.strip()
    roc_year = int(roc_ym[:-2])
    month = int(roc_ym[-2:])
    return f"{roc_year + 1911:04d}-{month:02d}"


def roc_date_to_western(roc_date: str) -> dt.date:
    """民國日期字串(如 '1150810')轉西元 date;格式不對就回傳今天(容錯)。"""
    roc_date = roc_date.strip()
    if len(roc_date) < 6 or not roc_date.isdigit():
        return dt.date.today()
    roc_year = int(roc_date[:-4])
    month = int(roc_date[-4:-2])
    day = int(roc_date[-2:])
    return dt.date(roc_year + 1911, month, day)
