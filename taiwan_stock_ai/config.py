"""集中管理設定值。全部從環境變數讀取,提供合理預設值。

MVP 原則:不寫死任何金鑰或路徑到程式碼裡,方便本地開發、GitHub Actions、
未來換資料庫(DuckDB -> Postgres/Supabase)時只改這一份。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# 讓本地開發可以用 .env 檔案(不會 commit),CI/正式環境用真正的環境變數。
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # dotenv 是選用套件,沒裝也不應該讓整個系統掛掉
    pass

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = REPO_ROOT / "data" / "taiwan_stock.duckdb"


def _bool_env(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    # 資料庫
    duckdb_path: str = field(
        default_factory=lambda: os.getenv("DUCKDB_PATH", str(DEFAULT_DB_PATH))
    )

    # FinMind(備援資料源)
    finmind_token: str = field(default_factory=lambda: os.getenv("FINMIND_TOKEN", ""))
    finmind_hourly_limit: int = field(
        default_factory=lambda: int(os.getenv("FINMIND_HOURLY_LIMIT", "600"))
    )

    # LINE Messaging API
    line_channel_access_token: str = field(
        default_factory=lambda: os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
    )
    line_channel_secret: str = field(
        default_factory=lambda: os.getenv("LINE_CHANNEL_SECRET", "")
    )

    # HTTP 行為
    http_timeout_seconds: float = field(
        default_factory=lambda: float(os.getenv("HTTP_TIMEOUT_SECONDS", "20"))
    )
    http_max_retries: int = field(
        default_factory=lambda: int(os.getenv("HTTP_MAX_RETRIES", "3"))
    )
    http_user_agent: str = field(
        default_factory=lambda: os.getenv(
            "HTTP_USER_AGENT",
            "taiwan-stock-ai-mvp/0.1 (personal research use; contact via LINE bot owner)",
        )
    )

    # 法遵:MVP 僅供開發者本人自用查詢,不對外開放、不收費、不作為投資建議。
    personal_use_only: bool = field(
        default_factory=lambda: _bool_env("PERSONAL_USE_ONLY", True)
    )


settings = Settings()
