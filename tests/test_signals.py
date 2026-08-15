from __future__ import annotations

import datetime as dt

from taiwan_stock_ai.signals.engine import (
    Bar,
    TAG_DAY_TRADE,
    TAG_SWING,
    compute_signals_for_stock,
    detect_intraday_momentum,
    detect_ma_breakout,
    detect_momentum,
    run_signal_engine,
)
from taiwan_stock_ai.signals.indicators import average, pct_change, rolling_high, rolling_low, simple_moving_average
from taiwan_stock_ai.storage.db import upsert_rows

BASE_DATE = dt.date(2026, 1, 1)


def _bars(closes: list[float], volumes: list[float]) -> list[Bar]:
    return [
        Bar(trade_date=BASE_DATE + dt.timedelta(days=i), close=c, volume=v)
        for i, (c, v) in enumerate(zip(closes, volumes))
    ]


# ---- indicators.py ----------------------------------------------------


def test_simple_moving_average_basic():
    sma = simple_moving_average([1, 2, 3, 4, 5], window=3)
    assert sma == [None, None, 2.0, 3.0, 4.0]


def test_simple_moving_average_rejects_non_positive_window():
    import pytest

    with pytest.raises(ValueError):
        simple_moving_average([1, 2, 3], window=0)


def test_pct_change():
    assert pct_change([100, 110], periods=1) == 0.1
    assert pct_change([100], periods=1) is None  # 資料不足
    assert pct_change([0, 10], periods=1) is None  # 基期為 0


def test_average_ignores_none():
    assert average([1.0, None, 3.0]) == 2.0
    assert average([None, None]) is None


def test_rolling_high_low():
    assert rolling_high([1, 5, 3], window=3) == 5
    assert rolling_low([1, 5, 3], window=3) == 1
    assert rolling_high([1, 5, 3], window=5) is None  # 資料不足


# ---- engine.py: 動量 -----------------------------------------------------


def test_detect_momentum_bullish():
    closes = [100.0] * 20 + [101, 103, 105, 108, 110, 112]
    volumes = [1000.0] * 25 + [2500.0]
    signal = detect_momentum(_bars(closes, volumes))
    assert signal is not None
    assert signal.tag == TAG_SWING
    assert signal.direction == "bullish"


def test_detect_momentum_bearish():
    closes = [100.0] * 20 + [99, 97, 95, 92, 90, 88]
    volumes = [1000.0] * 25 + [2500.0]
    signal = detect_momentum(_bars(closes, volumes))
    assert signal is not None
    assert signal.direction == "bearish"


def test_detect_momentum_no_signal_without_volume_confirmation():
    closes = [100.0] * 20 + [101, 103, 105, 108, 110, 112]
    volumes = [1000.0] * 26  # 量沒有放大
    assert detect_momentum(_bars(closes, volumes)) is None


def test_detect_momentum_insufficient_history():
    assert detect_momentum(_bars([100.0] * 5, [1000.0] * 5)) is None


# ---- engine.py: 單日動量(當沖候選) --------------------------------------


def test_detect_intraday_momentum_bullish_tagged_day_trade():
    closes = [100.0] * 10 + [100, 100, 100, 100, 100, 111]
    volumes = [1000.0] * 15 + [3000.0]
    signal = detect_intraday_momentum(_bars(closes, volumes))
    assert signal is not None
    assert signal.tag == TAG_DAY_TRADE
    assert signal.direction == "bullish"


def test_detect_intraday_momentum_none_without_big_move():
    closes = [100.0] * 16
    volumes = [1000.0] * 16
    assert detect_intraday_momentum(_bars(closes, volumes)) is None


# ---- engine.py: 均線糾纏突破 ----------------------------------------------


def _entangled_then_breakout(direction: str = "up") -> tuple[list[float], list[float]]:
    closes = [100.0] * 20
    for i in range(20):
        closes.append(100 + i * 0.05)  # 緩步盤整,MA5/MA20 仍貼近
    if direction == "up":
        closes.append(115.0)
    else:
        closes.append(85.0)
    volumes = [1000.0] * 39 + [3000.0]
    return closes, volumes


def test_detect_ma_breakout_bullish():
    closes, volumes = _entangled_then_breakout("up")
    signal = detect_ma_breakout(_bars(closes, volumes))
    assert signal is not None
    assert signal.tag == TAG_SWING
    assert signal.direction == "bullish"


def test_detect_ma_breakout_none_without_entanglement():
    # 均線一路發散,從沒糾纏過 -> 不該觸發
    closes = [100 + i * 2.0 for i in range(40)]
    volumes = [1000.0] * 39 + [3000.0]
    assert detect_ma_breakout(_bars(closes, volumes)) is None


def test_compute_signals_for_stock_aggregates_all_detectors():
    closes, volumes = _entangled_then_breakout("up")
    signals = compute_signals_for_stock(_bars(closes, volumes))
    names = {s.signal_name for s in signals}
    assert "ma_breakout" in names


# ---- engine.py: run_signal_engine(含處置股排除) ---------------------------


def _seed_daily_quotes(conn, closes, volumes, stock_id="2330"):
    now = dt.datetime.now(dt.timezone.utc)
    rows = []
    for bar in _bars(closes, volumes):
        rows.append(
            {
                "trade_date": bar.trade_date,
                "stock_id": stock_id,
                "stock_name": "台積電",
                "market": "TWSE",
                "open": bar.close,
                "high": bar.close,
                "low": bar.close,
                "close": bar.close,
                "volume_shares": bar.volume,
                "value_twd": bar.volume * bar.close,
                "change": 0.0,
                "transaction_count": 100,
                "fetched_at": now,
                "source": "test",
            }
        )
    upsert_rows(conn, "daily_quotes", rows, key_columns=["trade_date", "stock_id"])
    return rows[-1]["trade_date"]


def test_run_signal_engine_writes_signals(db_conn):
    closes = [100.0] * 10 + [100, 100, 100, 100, 100, 111]
    volumes = [1000.0] * 15 + [3000.0]
    signal_date = _seed_daily_quotes(db_conn, closes, volumes)

    n = run_signal_engine(db_conn, signal_date)
    assert n >= 1

    rows = db_conn.execute("SELECT tag, excluded_reason FROM signals WHERE stock_id='2330'").fetchall()
    assert any(tag == TAG_DAY_TRADE for tag, _ in rows)
    # 沒有處置股紀錄時,不應該被排除
    assert all(excluded is None for _, excluded in rows)


def test_run_signal_engine_excludes_disposition_stock_from_day_trade(db_conn):
    closes = [100.0] * 10 + [100, 100, 100, 100, 100, 111]
    volumes = [1000.0] * 15 + [3000.0]
    signal_date = _seed_daily_quotes(db_conn, closes, volumes)

    upsert_rows(
        db_conn,
        "disposition_stocks",
        [
            {
                "stock_id": "2330",
                "start_date": signal_date - dt.timedelta(days=1),
                "end_date": signal_date + dt.timedelta(days=5),
                "reason": "test disposition",
                "fetched_at": dt.datetime.now(dt.timezone.utc),
                "source": "test",
            }
        ],
        key_columns=["stock_id", "start_date"],
    )

    run_signal_engine(db_conn, signal_date)

    rows = db_conn.execute(
        "SELECT excluded_reason FROM signals WHERE stock_id='2330' AND tag=?", [TAG_DAY_TRADE]
    ).fetchall()
    assert rows, "expected at least one day-trade tagged signal"
    assert all(reason is not None for (reason,) in rows)
