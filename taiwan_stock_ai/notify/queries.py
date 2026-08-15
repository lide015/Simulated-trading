"""模組六:LINE Bot 查詢邏輯——純讀取事實表/訊號表,不寫入、不呼叫 LLM。

Dispatcher 本身就是報告一直強調的「規則引擎」實例:用關鍵字/正則比對決定
要走哪個查詢,再用 `notify.templates` 組字串回覆,全程 0 token。
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Any

import duckdb

from taiwan_stock_ai.notify import templates

_STOCK_CODE_RE = re.compile(r"^[0-9]{4,6}[A-Z]?$")
_DAY_TRADE_KEYWORDS_ZH = ("當沖選股", "當沖")
_DAY_TRADE_KEYWORDS_EN = ("day trade", "daytrade")
_HELP_KEYWORDS = ("help", "說明", "指令", "?", "？")


def is_stock_code(text: str) -> bool:
    return bool(_STOCK_CODE_RE.match(text.strip().upper()))


def _latest_quote(conn: duckdb.DuckDBPyConnection, stock_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT trade_date, stock_id, stock_name, close, change
        FROM daily_quotes
        WHERE stock_id = ?
        ORDER BY trade_date DESC
        LIMIT 1
        """,
        [stock_id],
    ).fetchone()
    if row is None:
        return None
    cols = ["trade_date", "stock_id", "stock_name", "close", "change"]
    return dict(zip(cols, row))


def _latest_signals(conn: duckdb.DuckDBPyConnection, stock_id: str) -> list[dict[str, Any]]:
    latest = conn.execute(
        "SELECT MAX(signal_date) FROM signals WHERE stock_id = ?", [stock_id]
    ).fetchone()
    latest_date = latest[0] if latest else None
    if latest_date is None:
        return []
    rows = conn.execute(
        """
        SELECT signal_name, tag, direction, strength, description, excluded_reason
        FROM signals
        WHERE stock_id = ? AND signal_date = ?
        ORDER BY strength DESC
        """,
        [stock_id, latest_date],
    ).fetchall()
    cols = ["signal_name", "tag", "direction", "strength", "description", "excluded_reason"]
    return [dict(zip(cols, r)) for r in rows]


def handle_stock_query(conn: duckdb.DuckDBPyConnection, stock_id: str) -> str:
    stock_id = stock_id.strip().upper()
    quote = _latest_quote(conn, stock_id)
    if quote is None:
        return templates.render_not_found(stock_id)
    signals = _latest_signals(conn, stock_id)
    return templates.render_stock_signals(stock_id, quote, signals)


def handle_day_trade_list(conn: duckdb.DuckDBPyConnection) -> str:
    latest = conn.execute("SELECT MAX(signal_date) FROM signals").fetchone()
    latest_date = latest[0] if latest else None
    if latest_date is None:
        return templates.render_day_trade_list(dt.date.today(), [])

    rows = conn.execute(
        """
        SELECT s.stock_id, q.stock_name, s.direction, s.description
        FROM signals s
        LEFT JOIN daily_quotes q
          ON q.stock_id = s.stock_id AND q.trade_date = s.signal_date
        WHERE s.signal_date = ? AND s.tag = '當沖' AND s.excluded_reason IS NULL
        ORDER BY s.strength DESC
        LIMIT 20
        """,
        [latest_date],
    ).fetchall()
    cols = ["stock_id", "stock_name", "direction", "description"]
    result_rows = [dict(zip(cols, r)) for r in rows]
    return templates.render_day_trade_list(latest_date, result_rows)


def handle_query(conn: duckdb.DuckDBPyConnection, text: str) -> str:
    """純規則(0 token)dispatcher。"""
    normalized = text.strip()
    lower = normalized.lower()

    if any(k in normalized for k in _DAY_TRADE_KEYWORDS_ZH) or any(
        k in lower for k in _DAY_TRADE_KEYWORDS_EN
    ):
        return handle_day_trade_list(conn)
    if is_stock_code(normalized):
        return handle_stock_query(conn, normalized)
    return templates.render_help()
