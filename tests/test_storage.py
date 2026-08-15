from __future__ import annotations

import datetime as dt

from taiwan_stock_ai.storage.db import log_fetch_result, missing_fetch_dates, upsert_rows


def _sample_quote(**overrides):
    row = {
        "trade_date": dt.date(2026, 8, 14),
        "stock_id": "2330",
        "stock_name": "台積電",
        "market": "TWSE",
        "open": 1000.0,
        "high": 1010.0,
        "low": 995.0,
        "close": 1005.0,
        "volume_shares": 12345678,
        "value_twd": 123456789,
        "change": 5.0,
        "transaction_count": 5555,
        "fetched_at": dt.datetime.now(dt.timezone.utc),
        "source": "test",
    }
    row.update(overrides)
    return row


def test_upsert_is_idempotent(db_conn):
    row = _sample_quote()
    n1 = upsert_rows(db_conn, "daily_quotes", [row], key_columns=["trade_date", "stock_id"])
    n2 = upsert_rows(db_conn, "daily_quotes", [row], key_columns=["trade_date", "stock_id"])

    assert n1 == 1
    assert n2 == 1
    count = db_conn.execute("SELECT COUNT(*) FROM daily_quotes").fetchone()[0]
    assert count == 1


def test_upsert_overwrites_changed_values(db_conn):
    row = _sample_quote(close=1005.0)
    upsert_rows(db_conn, "daily_quotes", [row], key_columns=["trade_date", "stock_id"])

    updated = _sample_quote(close=1099.0)
    upsert_rows(db_conn, "daily_quotes", [updated], key_columns=["trade_date", "stock_id"])

    close = db_conn.execute(
        "SELECT close FROM daily_quotes WHERE stock_id = '2330' AND trade_date = '2026-08-14'"
    ).fetchone()[0]
    assert close == 1099.0


def test_upsert_empty_rows_returns_zero(db_conn):
    assert upsert_rows(db_conn, "daily_quotes", [], key_columns=["trade_date", "stock_id"]) == 0


def test_missing_fetch_dates(db_conn):
    log_fetch_result(
        db_conn, dataset="daily_quotes_twse", fetch_date=dt.date(2026, 8, 12), status="success", row_count=100
    )
    log_fetch_result(
        db_conn, dataset="daily_quotes_twse", fetch_date=dt.date(2026, 8, 13), status="failed", error_message="boom"
    )

    candidates = [dt.date(2026, 8, 12), dt.date(2026, 8, 13), dt.date(2026, 8, 14)]
    missing = missing_fetch_dates(db_conn, dataset="daily_quotes_twse", candidate_dates=candidates)

    # 8/12 成功過,不算缺漏;8/13 失敗過與 8/14 從沒抓過,都算缺漏。
    assert set(missing) == {dt.date(2026, 8, 13), dt.date(2026, 8, 14)}
