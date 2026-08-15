"""共用的 HTTP 存取層:重試/退避 + 節流器。

報告裡強調的「禮貌性」規則(TWSE 自行節流、twstock 5 秒 3 次、FinMind
600/hr)都在這一層集中處理,個別 client 不用重複寫。
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Any

import requests

from taiwan_stock_ai.config import settings

logger = logging.getLogger(__name__)


class RateLimiter:
    """滑動視窗節流器:同一時間視窗內最多 max_calls 次呼叫。

    執行緒安全,阻塞式(超過限制就 sleep 到視窗解鎖),適合排程批次抓取。
    """

    def __init__(self, max_calls: int, period_seconds: float) -> None:
        if max_calls <= 0:
            raise ValueError("max_calls must be positive")
        self.max_calls = max_calls
        self.period_seconds = period_seconds
        self._calls: deque[float] = deque()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        with self._lock:
            now = time.monotonic()
            while self._calls and now - self._calls[0] >= self.period_seconds:
                self._calls.popleft()

            if len(self._calls) >= self.max_calls:
                sleep_for = self.period_seconds - (now - self._calls[0])
                if sleep_for > 0:
                    logger.info("rate limit reached, sleeping %.1fs", sleep_for)
                    time.sleep(sleep_for)
                now = time.monotonic()
                while self._calls and now - self._calls[0] >= self.period_seconds:
                    self._calls.popleft()

            self._calls.append(time.monotonic())


class HttpError(RuntimeError):
    """包裝所有 HTTP 失敗情況,讓上層可以統一處理告警。"""


def get_json(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    rate_limiter: RateLimiter | None = None,
    retries: int | None = None,
    backoff_base: float = 2.0,
    timeout: float | None = None,
) -> Any:
    """GET 一個 JSON API,失敗時用指數退避重試。

    對應報告要求:「自行節流＋重試＋快取」。快取(避免重複抓當日已抓過的
    資料)交給呼叫端搭配 storage 層的 upsert 冪等性處理,這裡只管網路層。
    """
    retries = settings.http_max_retries if retries is None else retries
    timeout = settings.http_timeout_seconds if timeout is None else timeout
    merged_headers = {"User-Agent": settings.http_user_agent, "Accept": "application/json"}
    if headers:
        merged_headers.update(headers)

    last_exc: Exception | None = None
    for attempt in range(1, retries + 1):
        if rate_limiter is not None:
            rate_limiter.acquire()
        try:
            resp = requests.get(url, params=params, headers=merged_headers, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except (requests.RequestException, ValueError) as exc:
            last_exc = exc
            if attempt == retries:
                break
            sleep_for = backoff_base ** attempt
            logger.warning(
                "GET %s failed (attempt %d/%d): %s; retrying in %.1fs",
                url,
                attempt,
                retries,
                exc,
                sleep_for,
            )
            time.sleep(sleep_for)

    raise HttpError(f"GET {url} failed after {retries} attempts: {last_exc}") from last_exc
