from __future__ import annotations

import datetime as dt

from taiwan_stock_ai.notify.queries import handle_query, is_stock_code
from taiwan_stock_ai.signals.engine import run_signal_engine
from taiwan_stock_ai.storage.db import upsert_rows


def test_is_stock_code():
    assert is_stock_code("2330")
    assert is_stock_code("00631L")
    assert not is_stock_code("今日當沖選股")
    assert not is_stock_code("hello world")


def test_handle_query_help_for_unrecognized_text(db_conn):
    reply = handle_query(db_conn, "隨便打的東西")
    assert "可用指令" in reply


def test_handle_query_not_found_for_unknown_stock(db_conn):
    reply = handle_query(db_conn, "9999")
    assert "查無" in reply


def _seed_momentum_signal(conn, stock_id="2330"):
    base = dt.date(2026, 1, 1)
    closes = [100.0] * 10 + [100, 100, 100, 100, 100, 111]
    volumes = [1000.0] * 15 + [3000.0]
    now = dt.datetime.now(dt.timezone.utc)
    rows = []
    for i, (c, v) in enumerate(zip(closes, volumes)):
        d = base + dt.timedelta(days=i)
        rows.append(
            {
                "trade_date": d,
                "stock_id": stock_id,
                "stock_name": "台積電",
                "market": "TWSE",
                "open": c,
                "high": c,
                "low": c,
                "close": c,
                "volume_shares": v,
                "value_twd": v * c,
                "change": 0.0,
                "transaction_count": 100,
                "fetched_at": now,
                "source": "test",
            }
        )
    upsert_rows(conn, "daily_quotes", rows, key_columns=["trade_date", "stock_id"])
    signal_date = rows[-1]["trade_date"]
    run_signal_engine(conn, signal_date)
    return signal_date


def test_handle_query_stock_code_returns_signal(db_conn):
    _seed_momentum_signal(db_conn)
    reply = handle_query(db_conn, "2330")
    assert "2330" in reply
    assert "當沖" in reply  # intraday_momentum 訊號應該出現
    assert "非投資建議" in reply


def test_handle_query_day_trade_list(db_conn):
    _seed_momentum_signal(db_conn)
    for keyword in ("今日當沖選股", "當沖"):
        reply = handle_query(db_conn, keyword)
        assert "2330" in reply
        assert "候選觀察清單" in reply


def test_day_trade_list_excludes_disposition_stock(db_conn):
    signal_date = _seed_momentum_signal(db_conn)
    upsert_rows(
        db_conn,
        "disposition_stocks",
        [
            {
                "stock_id": "2330",
                "start_date": signal_date,
                "end_date": None,
                "reason": "test",
                "fetched_at": dt.datetime.now(dt.timezone.utc),
                "source": "test",
            }
        ],
        key_columns=["stock_id", "start_date"],
    )
    # 重新跑一次訊號引擎,讓排除邏輯生效
    run_signal_engine(db_conn, signal_date)

    reply = handle_query(db_conn, "今日當沖選股")
    assert "2330" not in reply
    assert "無符合條件" in reply
