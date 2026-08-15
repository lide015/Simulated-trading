"""純 Python 技術指標計算。

刻意不依賴 pandas/ta-lib:訊號引擎的每一步都要能在沒裝額外套件的情況下
單元測試,也呼應報告「規則引擎為主、0 token」的精神——連指標計算都不需要
拉重型別的資料科學堆疊。
"""
from __future__ import annotations


def simple_moving_average(closes: list[float], window: int) -> list[float | None]:
    """回傳與 closes 等長的 SMA 序列;資料不足 window 天的位置為 None。"""
    if window <= 0:
        raise ValueError("window must be positive")

    result: list[float | None] = [None] * len(closes)
    running_sum = 0.0
    for i, price in enumerate(closes):
        running_sum += price
        if i >= window:
            running_sum -= closes[i - window]
        if i >= window - 1:
            result[i] = running_sum / window
    return result


def pct_change(closes: list[float], periods: int) -> float | None:
    """相对 `periods` 天前的漲跌幅。資料不足或基期為 0 時回傳 None。"""
    if periods <= 0 or len(closes) <= periods:
        return None
    base = closes[-1 - periods]
    if not base:
        return None
    return (closes[-1] - base) / base


def average(values: list[float | None]) -> float | None:
    clean = [v for v in values if v is not None]
    if not clean:
        return None
    return sum(clean) / len(clean)


def rolling_high(values: list[float], window: int) -> float | None:
    if len(values) < window:
        return None
    return max(values[-window:])


def rolling_low(values: list[float], window: int) -> float | None:
    if len(values) < window:
        return None
    return min(values[-window:])
