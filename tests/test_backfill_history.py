from __future__ import annotations

import datetime as dt

from taiwan_stock_ai.data import finmind_client
from taiwan_stock_ai.scheduler import backfill_history
from taiwan_stock_ai.storage.db import upsert_rows


def _seed_today_snapshot(conn):
    """模擬 STOCK_DAY_ALL 已經跑過一次,事實表裡有今天的完整快照。"""
    now = dt.datetime.now(dt.timezone.utc)
    today = dt.date.today()
    rows = [
        {
            "trade_date": today, "stock_id": "2330", "stock_name": "台積電", "market": "TWSE",
            "open": 1000.0, "high": 1010.0, "low": 995.0, "close": 1005.0,
            "volume_shares": 1000, "value_twd": 5_000_000, "change": 5.0,
            "transaction_count": 100, "fetched_at": now, "source": "test",
        },
        {
            "trade_date": today, "stock_id": "2454", "stock_name": "聯發科", "market": "TWSE",
            "open": 800.0, "high": 810.0, "low": 795.0, "close": 805.0,
            "volume_shares": 500, "value_twd": 1_000_000, "change": -2.0,
            "transaction_count": 50, "fetched_at": now, "source": "test",
        },
    ]
    upsert_rows(conn, "daily_quotes", rows, key_columns=["trade_date", "stock_id"])
    return today


def _fake_finmind_rows(stock_id: str, start_date: dt.date, n_days: int = 3) -> list[dict]:
    now = dt.datetime.now(dt.timezone.utc)
    return [
        {
            "trade_date": start_date + dt.timedelta(days=i),
            "stock_id": stock_id,
            "stock_name": None,  # FinMind 不回公司名稱
            "market": "TWSE/TPEx",
            "open": 100.0 + i, "high": 101.0 + i, "low": 99.0 + i, "close": 100.5 + i,
            "volume_shares": 1000, "value_twd": 100500, "change": 0.5,
            "transaction_count": 10, "fetched_at": now, "source": "finmind:TaiwanStockPrice",
        }
        for i in range(n_days)
    ]


def test_pick_top_stock_ids_orders_by_value_desc(db_conn):
    _seed_today_snapshot(db_conn)
    ids = backfill_history.pick_top_stock_ids(db_conn, limit=10)
    assert ids == ["2330", "2454"]  # 2330 成交值較高,排前面


def test_pick_top_stock_ids_respects_limit(db_conn):
    _seed_today_snapshot(db_conn)
    assert backfill_history.pick_top_stock_ids(db_conn, limit=1) == ["2330"]


def test_run_backfill_fills_missing_stock_name(db_conn, monkeypatch):
    today = _seed_today_snapshot(db_conn)
    monkeypatch.setattr(
        finmind_client, "fetch_stock_price",
        lambda stock_id, start_date, end_date=None: _fake_finmind_rows(stock_id, start_date),
    )

    results = backfill_history.run_backfill(db_conn, ["2330"], days=3)
    assert results["2330"] == 3

    rows = db_conn.execute(
        "SELECT trade_date, stock_name FROM daily_quotes WHERE stock_id = '2330' ORDER BY trade_date"
    ).fetchall()
    # 補回來的歷史列(不含今天那筆)都該被填上「台積電」,不是 NULL
    backfilled = [r for r in rows if r[0] != today]
    assert backfilled, "應該至少補到一筆歷史資料"
    assert all(name == "台積電" for _, name in backfilled)


def test_run_backfill_isolates_per_stock_failure(db_conn, monkeypatch):
    _seed_today_snapshot(db_conn)

    def flaky_fetch(stock_id, start_date, end_date=None):
        if stock_id == "2454":
            raise RuntimeError("FinMind 掛了")
        return _fake_finmind_rows(stock_id, start_date)

    monkeypatch.setattr(finmind_client, "fetch_stock_price", flaky_fetch)

    results = backfill_history.run_backfill(db_conn, ["2330", "2454"], days=3)
    assert results["2330"] == 3
    assert results["2454"] == 0  # 失敗記 0,不會拋例外炸掉整批


class _NoCloseConnWrapper:
    """main() 執行完會呼叫 conn.close(),但這裡想在那之後繼續用同一個連線
    檢查結果。DuckDBPyConnection 是 C extension type,屬性唯讀,沒辦法直接
    monkeypatch 它的 close 方法,所以包一層 wrapper 把 close() 變 no-op,
    其餘方法都轉呼叫真正的連線。
    """

    def __init__(self, real_conn):
        self._real = real_conn

    def close(self) -> None:
        pass

    def __getattr__(self, name):
        return getattr(self._real, name)


def test_main_backfills_using_auto_selected_stocks(db_conn, monkeypatch):
    import taiwan_stock_ai.scheduler.backfill_history as mod

    _seed_today_snapshot(db_conn)
    monkeypatch.setattr(mod, "get_connection", lambda *a, **k: _NoCloseConnWrapper(db_conn))
    monkeypatch.setattr(
        finmind_client, "fetch_stock_price",
        lambda stock_id, start_date, end_date=None: _fake_finmind_rows(stock_id, start_date),
    )

    rc = mod.main(["--limit", "2", "--days", "3"])
    assert rc == 0

    count = db_conn.execute("SELECT COUNT(*) FROM daily_quotes").fetchone()[0]
    assert count > 2  # 原本的 2 筆快照 + 補回來的歷史列
