"""模組三:本地訊號引擎(0 token)。

依報告「五、技術指標正確性與證據強度」的結論:動量與均線是相對證據較強、
最容易解釋的兩個訊號,MVP 只做這兩個,且一律用**描述性**語言
(「出現量增價漲」)而不是**結果預測/推介性**語言(「建議買進」)——
這既是報告點名的「壞標籤」反模式紅線,也是自用系統萬一未來考慮公開時的
法遵緩衝(《證券投資信託及顧問法》第 4、6 條)。

當沖合規安全網:任何標記【當沖】的訊號,一律先比對處置股清單
(disposition_stocks),命中就標 excluded_reason 並且不會出現在
LINE Bot「今日當沖選股」清單裡。
"""
from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from typing import Any

import duckdb

from taiwan_stock_ai.signals.indicators import average, pct_change, rolling_high, rolling_low, simple_moving_average
from taiwan_stock_ai.storage.db import upsert_rows

logger = logging.getLogger(__name__)

TAG_DAY_TRADE = "當沖"
TAG_SWING = "波段"
TAG_LONG_TERM = "中長線"

DIRECTION_BULLISH = "bullish"
DIRECTION_BEARISH = "bearish"


@dataclass
class Bar:
    trade_date: dt.date
    close: float
    volume: float


@dataclass
class SignalResult:
    signal_name: str
    tag: str
    direction: str
    strength: float
    description: str


def detect_momentum(
    bars: list[Bar],
    *,
    lookback: int = 5,
    return_threshold: float = 0.08,
    volume_ratio_threshold: float = 1.5,
) -> SignalResult | None:
    """量增價強動量(波段版):N 日累積漲跌幅夠大 + 量能同步放大。"""
    if len(bars) < lookback + 6:
        return None

    closes = [b.close for b in bars]
    volumes = [b.volume for b in bars]

    ret = pct_change(closes, lookback)
    if ret is None:
        return None

    recent_avg_volume = average(volumes[-(lookback + 1) : -1])
    if not recent_avg_volume:
        return None
    volume_ratio = volumes[-1] / recent_avg_volume

    if ret >= return_threshold and volume_ratio >= volume_ratio_threshold:
        return SignalResult(
            signal_name="momentum",
            tag=TAG_SWING,
            direction=DIRECTION_BULLISH,
            strength=round(ret * volume_ratio, 4),
            description=f"近{lookback}日累積漲幅 {ret:+.1%},量能為近期均量 {volume_ratio:.1f} 倍(量增價漲)",
        )
    if ret <= -return_threshold and volume_ratio >= volume_ratio_threshold:
        return SignalResult(
            signal_name="momentum",
            tag=TAG_SWING,
            direction=DIRECTION_BEARISH,
            strength=round(abs(ret) * volume_ratio, 4),
            description=f"近{lookback}日累積跌幅 {ret:+.1%},量能為近期均量 {volume_ratio:.1f} 倍(量增價跌)",
        )
    return None


def detect_intraday_momentum(
    bars: list[Bar],
    *,
    return_threshold: float = 0.05,
    volume_ratio_threshold: float = 2.0,
) -> SignalResult | None:
    """單日爆量急漲跌(當沖候選觀察,非隔日沖買賣建議)。"""
    if len(bars) < 7:
        return None

    closes = [b.close for b in bars]
    volumes = [b.volume for b in bars]

    ret = pct_change(closes, 1)
    if ret is None:
        return None

    recent_avg_volume = average(volumes[-6:-1])
    if not recent_avg_volume:
        return None
    volume_ratio = volumes[-1] / recent_avg_volume

    if ret >= return_threshold and volume_ratio >= volume_ratio_threshold:
        return SignalResult(
            signal_name="intraday_momentum",
            tag=TAG_DAY_TRADE,
            direction=DIRECTION_BULLISH,
            strength=round(ret * volume_ratio, 4),
            description=f"單日漲幅 {ret:+.1%}、成交量為近5日均量 {volume_ratio:.1f} 倍,列入隔日觀察候選(非買賣建議)",
        )
    if ret <= -return_threshold and volume_ratio >= volume_ratio_threshold:
        return SignalResult(
            signal_name="intraday_momentum",
            tag=TAG_DAY_TRADE,
            direction=DIRECTION_BEARISH,
            strength=round(abs(ret) * volume_ratio, 4),
            description=f"單日跌幅 {ret:+.1%}、成交量為近5日均量 {volume_ratio:.1f} 倍,列入隔日觀察候選(非買賣建議)",
        )
    return None


def detect_ma_breakout(
    bars: list[Bar],
    *,
    short_window: int = 5,
    long_window: int = 20,
    entangle_days: int = 5,
    entangle_pct: float = 0.015,
    breakout_lookback: int = 20,
    volume_ratio_threshold: float = 1.2,
) -> SignalResult | None:
    """均線糾纏突破:短期均線與長期均線黏著一段時間後,價格帶量突破近期高/低點。"""
    if len(bars) < long_window + entangle_days + 1:
        return None

    closes = [b.close for b in bars]
    volumes = [b.volume for b in bars]

    ma_short = simple_moving_average(closes, short_window)
    ma_long = simple_moving_average(closes, long_window)

    # 糾纏判定:過去 entangle_days 天(不含今天),短長均線的差距相對股價都很小
    spread_window = []
    for i in range(-entangle_days - 1, -1):
        s, l = ma_short[i], ma_long[i]
        if s is None or l is None or closes[i] == 0:
            return None
        spread_window.append(abs(s - l) / closes[i])
    if max(spread_window) > entangle_pct:
        return None  # 過去沒有糾纏,不算突破

    today_short, today_long = ma_short[-1], ma_long[-1]
    if today_short is None or today_long is None:
        return None

    recent_avg_volume = average(volumes[-(entangle_days + 1) : -1])
    if not recent_avg_volume:
        return None
    volume_ratio = volumes[-1] / recent_avg_volume
    if volume_ratio < volume_ratio_threshold:
        return None

    prior_high = rolling_high(closes[:-1], breakout_lookback)
    prior_low = rolling_low(closes[:-1], breakout_lookback)
    today_close = closes[-1]

    if today_short > today_long and prior_high is not None and today_close > prior_high:
        return SignalResult(
            signal_name="ma_breakout",
            tag=TAG_SWING,
            direction=DIRECTION_BULLISH,
            strength=round((today_close / prior_high - 1) * volume_ratio, 4),
            description=(
                f"{short_window}日均線與{long_window}日均線糾纏{entangle_days}日後向上突破,"
                f"收盤價創近{breakout_lookback}日新高,量能為近期均量 {volume_ratio:.1f} 倍"
            ),
        )
    if today_short < today_long and prior_low is not None and today_close < prior_low:
        return SignalResult(
            signal_name="ma_breakout",
            tag=TAG_SWING,
            direction=DIRECTION_BEARISH,
            strength=round((1 - today_close / prior_low) * volume_ratio, 4),
            description=(
                f"{short_window}日均線與{long_window}日均線糾纏{entangle_days}日後向下跌破,"
                f"收盤價創近{breakout_lookback}日新低,量能為近期均量 {volume_ratio:.1f} 倍"
            ),
        )
    return None


ALL_DETECTORS = (detect_momentum, detect_intraday_momentum, detect_ma_breakout)


def compute_signals_for_stock(bars: list[Bar]) -> list[SignalResult]:
    """對單一股票的歷史 K 棒(已依日期升冪排序)跑全部訊號偵測器。"""
    results = []
    for detector in ALL_DETECTORS:
        signal = detector(bars)
        if signal is not None:
            results.append(signal)
    return results


def _is_under_disposition(
    conn: duckdb.DuckDBPyConnection, stock_id: str, signal_date: dt.date
) -> bool:
    row = conn.execute(
        """
        SELECT 1 FROM disposition_stocks
        WHERE stock_id = ?
          AND start_date <= ?
          AND (end_date IS NULL OR end_date >= ?)
        LIMIT 1
        """,
        [stock_id, signal_date, signal_date],
    ).fetchone()
    return row is not None


def run_signal_engine(
    conn: duckdb.DuckDBPyConnection,
    signal_date: dt.date | None = None,
    *,
    history_window: int = 60,
) -> int:
    """對事實表裡有足夠歷史的每一檔股票跑訊號引擎,寫回 signals 表。

    回傳寫入的訊號筆數。
    """
    signal_date = signal_date or dt.date.today()

    stock_ids = [
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT stock_id FROM daily_quotes WHERE trade_date <= ?",
            [signal_date],
        ).fetchall()
    ]

    now = dt.datetime.now(dt.timezone.utc)
    rows: list[dict[str, Any]] = []

    for stock_id in stock_ids:
        history = conn.execute(
            """
            SELECT trade_date, close, volume_shares FROM daily_quotes
            WHERE stock_id = ? AND trade_date <= ?
            ORDER BY trade_date DESC LIMIT ?
            """,
            [stock_id, signal_date, history_window],
        ).fetchall()
        if not history:
            continue
        bars = [
            Bar(trade_date=r[0], close=r[1], volume=r[2] or 0)
            for r in reversed(history)
            if r[1] is not None
        ]
        if bars[-1].trade_date != signal_date:
            # 該股今天沒有收盤資料(停牌/未上市/資料缺漏),跳過。
            continue

        for signal in compute_signals_for_stock(bars):
            excluded_reason = None
            if signal.tag == TAG_DAY_TRADE and _is_under_disposition(conn, stock_id, signal_date):
                excluded_reason = "處置股,依規不可當沖,已排除於當沖候選清單"

            rows.append(
                {
                    "signal_date": signal_date,
                    "stock_id": stock_id,
                    "signal_name": signal.signal_name,
                    "tag": signal.tag,
                    "direction": signal.direction,
                    "strength": signal.strength,
                    "description": signal.description,
                    "excluded_reason": excluded_reason,
                    "computed_at": now,
                }
            )

    n = upsert_rows(conn, "signals", rows, key_columns=["signal_date", "stock_id", "signal_name"])
    logger.info("signal engine %s: %d signals from %d stocks", signal_date, n, len(stock_ids))
    return n


if __name__ == "__main__":
    import logging as _logging

    from taiwan_stock_ai.storage.db import get_connection

    _logging.basicConfig(level=_logging.INFO)
    _conn = get_connection()
    try:
        run_signal_engine(_conn)
    finally:
        _conn.close()
