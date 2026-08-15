from __future__ import annotations

import base64
import dataclasses
import hashlib
import hmac

import pytest
from fastapi.testclient import TestClient

from taiwan_stock_ai.notify import line_bot
from taiwan_stock_ai.storage.db import get_connection as real_get_connection


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = str(tmp_path / "line_bot_test.duckdb")
    monkeypatch.setattr(line_bot, "get_connection", lambda *a, **k: real_get_connection(db_path))
    return TestClient(line_bot.app)


def _with_secret(secret: str):
    return dataclasses.replace(line_bot.settings, line_channel_secret=secret)


def test_verify_signature_accepts_correct_hmac(monkeypatch):
    monkeypatch.setattr(line_bot, "settings", _with_secret("mysecret"))
    body = b'{"events": []}'
    mac = hmac.new(b"mysecret", body, hashlib.sha256)
    sig = base64.b64encode(mac.digest()).decode()
    assert line_bot.verify_signature(body, sig) is True


def test_verify_signature_rejects_wrong_hmac(monkeypatch):
    monkeypatch.setattr(line_bot, "settings", _with_secret("mysecret"))
    assert line_bot.verify_signature(b'{"events": []}', "bogus==") is False


def test_verify_signature_skips_when_no_secret_configured(monkeypatch):
    monkeypatch.setattr(line_bot, "settings", _with_secret(""))
    assert line_bot.verify_signature(b"anything", "whatever") is True


def test_webhook_rejects_bad_signature(client, monkeypatch):
    monkeypatch.setattr(line_bot, "settings", _with_secret("mysecret"))
    resp = client.post(
        "/webhook", content=b'{"events": []}', headers={"X-Line-Signature": "bogus"}
    )
    assert resp.status_code == 400


def test_webhook_replies_help_for_text_message(client, monkeypatch):
    monkeypatch.setattr(line_bot, "settings", _with_secret(""))  # 開發模式,略過簽章驗證

    replies: list[tuple[str, str]] = []

    async def fake_reply(reply_token, text):
        replies.append((reply_token, text))

    monkeypatch.setattr(line_bot, "_reply", fake_reply)

    body = {
        "events": [
            {"type": "message", "replyToken": "abc123", "message": {"type": "text", "text": "help"}}
        ]
    }
    resp = client.post("/webhook", json=body)

    assert resp.status_code == 200
    assert len(replies) == 1
    assert replies[0][0] == "abc123"
    assert "可用指令" in replies[0][1]


def test_webhook_ignores_non_text_events(client, monkeypatch):
    monkeypatch.setattr(line_bot, "settings", _with_secret(""))

    replies: list[tuple[str, str]] = []

    async def fake_reply(reply_token, text):
        replies.append((reply_token, text))

    monkeypatch.setattr(line_bot, "_reply", fake_reply)

    body = {"events": [{"type": "follow", "replyToken": "abc123"}]}
    resp = client.post("/webhook", json=body)

    assert resp.status_code == 200
    assert replies == []


def test_healthz(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
