#!/usr/bin/env python3
"""選用的 REST API 層(docs/CLAUDE_INTEGRATION.md 方案 3)。

方案 1(CLI copy-paste)是預設、零設定的路徑;這支只有在你真的需要讓
Claude(或其他外部程式)透過網路呼叫時才需要啟動,而且啟動後預設只聽
127.0.0.1,不會不小心對外暴露。所有邏輯都轉呼叫 decision_writer.py 的
`DecisionWriter` / `create_decision_from_dict`,不重寫一份。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

# 讓 `python scripts/api_server.py` 跟 `uvicorn scripts.api_server:app` 兩種
# 啟動方式都能找到同目錄的 decision_writer.py。
sys.path.insert(0, str(Path(__file__).resolve().parent))

from decision_writer import DecisionWriter, create_decision_from_dict, DEFAULT_DB_PATH  # noqa: E402
from fastapi import FastAPI, Header, HTTPException  # noqa: E402

API_KEY = os.getenv("API_KEY", "")

app = FastAPI(title="Simulated Trading API", version="0.1.0")
writer = DecisionWriter(os.getenv("DATABASE_PATH", DEFAULT_DB_PATH))


def _check_api_key(x_api_key: Optional[str]) -> None:
    """依 CLAUDE_INTEGRATION.md「用 API Key 保護端點」的建議:設了 API_KEY
    就強制驗證每個請求;沒設就放行,但只該用於本機開發(見啟動時的警告)。
    """
    if not API_KEY:
        return
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="invalid or missing X-API-Key")


@app.on_event("startup")
def _warn_if_unprotected() -> None:
    if not API_KEY:
        print(
            "⚠ API_KEY 未設定,/decisions 端點目前沒有驗證。"
            "只適合本機開發,請勿對外公開此服務。",
            file=sys.stderr,
        )


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/decisions")
def create_decision(payload: dict, x_api_key: Optional[str] = Header(default=None)):
    """建立一筆新的 DecisionRecord。

    Example:
        POST /decisions
        {"market_snapshot": {...}, "trader_state": {...}, "action": {...}}
    """
    _check_api_key(x_api_key)
    try:
        record = create_decision_from_dict(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if not writer.write_decision(record):
        raise HTTPException(status_code=409, detail=f"decision {record.id} already exists")
    return {"status": "ok", "id": record.id}


@app.get("/decisions/{decision_id}")
def read_decision(decision_id: str, x_api_key: Optional[str] = Header(default=None)):
    """依 ID 讀取單筆決策。"""
    _check_api_key(x_api_key)
    record = writer.read_decision(decision_id)
    if record is None:
        raise HTTPException(status_code=404, detail="not found")
    return record


@app.get("/stats")
def get_stats(x_api_key: Optional[str] = Header(default=None)):
    """資料庫統計資訊。"""
    _check_api_key(x_api_key)
    return writer.get_stats()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
