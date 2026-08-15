"""模組六:LINE Bot webhook(FastAPI)。

只做 Reply,不做主動 push——依報告「Reply 回覆訊息免費、不計入額度,主動
推播才計」,天然不會撞到 LINE 免費方案 200 則/月的上限。查詢邏輯與回覆
文字都是規則引擎(見 `queries.py`/`templates.py`),整條路徑 0 token。

法遵:依《證券投資信託及顧問法》,本 Bot 僅供開發者本人查詢自用,
`config.settings.personal_use_only` 是提醒用的旗標,不是技術上的存取控制
——這個 Bot 本來就不該對外公開 webhook URL 或分享給不特定人使用。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging

import httpx
from fastapi import FastAPI, Header, HTTPException, Request

from taiwan_stock_ai.config import settings
from taiwan_stock_ai.notify.queries import handle_query
from taiwan_stock_ai.storage.db import get_connection

logger = logging.getLogger(__name__)

app = FastAPI(title="taiwan-stock-ai LINE bot", version="0.1.0")

LINE_REPLY_URL = "https://api.line.me/v2/bot/message/reply"
_MAX_LINE_TEXT_LENGTH = 5000


def verify_signature(body: bytes, signature: str) -> bool:
    """驗證 LINE webhook 的 X-Line-Signature(HMAC-SHA256 + base64)。"""
    if not settings.line_channel_secret:
        logger.warning("LINE_CHANNEL_SECRET not set; skipping signature verification (dev only)")
        return True
    mac = hmac.new(settings.line_channel_secret.encode("utf-8"), body, hashlib.sha256)
    expected = base64.b64encode(mac.digest()).decode("utf-8")
    return hmac.compare_digest(expected, signature)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/webhook")
async def webhook(request: Request, x_line_signature: str = Header(default="")) -> dict[str, str]:
    body = await request.body()
    if not verify_signature(body, x_line_signature):
        raise HTTPException(status_code=400, detail="invalid signature")

    payload = await request.json()
    events = payload.get("events", [])

    conn = get_connection()
    try:
        for event in events:
            await _handle_event(conn, event)
    finally:
        conn.close()

    return {"status": "ok"}


async def _handle_event(conn, event: dict) -> None:
    if event.get("type") != "message":
        return
    message = event.get("message", {})
    if message.get("type") != "text":
        return

    reply_token = event.get("replyToken")
    text = message.get("text", "")
    reply_text = handle_query(conn, text)
    await _reply(reply_token, reply_text)


async def _reply(reply_token: str, text: str) -> None:
    if not settings.line_channel_access_token:
        logger.warning(
            "LINE_CHANNEL_ACCESS_TOKEN not set; not sending. Reply would have been:\n%s", text
        )
        return

    headers = {
        "Authorization": f"Bearer {settings.line_channel_access_token}",
        "Content-Type": "application/json",
    }
    body = {
        "replyToken": reply_token,
        "messages": [{"type": "text", "text": text[:_MAX_LINE_TEXT_LENGTH]}],
    }
    async with httpx.AsyncClient(timeout=settings.http_timeout_seconds) as client:
        resp = await client.post(LINE_REPLY_URL, headers=headers, json=body)
        if resp.status_code >= 400:
            logger.error("LINE reply failed: %s %s", resp.status_code, resp.text)
