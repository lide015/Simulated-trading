"""dashboard/ 底下共用的邏輯:路徑設定、密碼保護、共用常數。

被 `dashboard/app.py`(前台,公開)跟 `dashboard/pages/*.py`(後台,受密碼
保護)一起 import,只寫一份——兩邊對「怎麼找到 repo 根目錄」「密碼怎麼
驗證」的認知不該分岔。
"""
from __future__ import annotations

import hmac
import os
import sys
from pathlib import Path

import streamlit as st

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

from taiwan_stock_ai.config import settings as ts_settings  # noqa: E402
from taiwan_stock_ai.notify.queries import handle_query as ts_handle_query  # noqa: E402
from decision_writer import DecisionWriter, DEFAULT_DB_PATH  # noqa: E402

__all__ = [
    "ts_settings",
    "ts_handle_query",
    "DecisionWriter",
    "DEFAULT_DB_PATH",
    "PUBLIC_DISCLAIMER",
    "ADMIN_DISCLAIMER",
    "require_password",
    "direction_color",
]

# 前台是公開頁面,措辭是一般的「非投資建議」提醒;後台會直接顯示交易決策
# 細節(信心度、實際下單參數),措辭額外加「請勿對外公開」——兩邊性質不同,
# 刻意用不同常數,不要共用同一句話。
PUBLIC_DISCLAIMER = "⚠ 資料僅供研究/參考用途,非投資建議,請自行判斷風險。"
ADMIN_DISCLAIMER = "⚠ 本頁僅供開發者本人研究用途,資料非投資建議,請勿對外公開。"

# 台灣慣例紅漲綠跌,跟歐美/加密貨幣常見的綠漲紅跌相反——這裡集中定義一次,
# 避免前台圖表跟後台之後如果也要標色時,兩邊配色邏輯兜不起來。
_UP_COLOR = "#e03131"
_DOWN_COLOR = "#2f9e44"
_FLAT_COLOR = "#868e96"


def direction_color(direction: str | None) -> str:
    """bullish/漲 → 紅,bearish/跌 → 綠,其餘(含 None)→ 灰。"""
    if direction in ("bullish", "up", "漲"):
        return _UP_COLOR
    if direction in ("bearish", "down", "跌"):
        return _DOWN_COLOR
    return _FLAT_COLOR


def _configured_password() -> str | None:
    """密碼來源:優先讀 Streamlit secrets(Community Cloud 用這個),
    本機開發沒有 secrets.toml 時退回讀環境變數 DASHBOARD_PASSWORD。"""
    try:
        return st.secrets["DASHBOARD_PASSWORD"]
    except Exception:  # noqa: BLE001 - 沒有 secrets.toml 或沒設這個 key 都算「沒設密碼」
        return os.environ.get("DASHBOARD_PASSWORD")


def require_password() -> None:
    """畫任何後台資料前的守門。已登入過的瀏覽器分頁(session_state)不用重輸。

    只有後台(`pages/1_後台管理.py`)呼叫這個函式——前台是刻意公開的,不
    應該也不會呼叫它。

    已知限制:這只是單一靜態密碼 + session_state,沒有失敗次數鎖定機制,
    擋不住有心人寫腳本硬猜。對「一個人自用、偶爾分享給自己手機看」這種
    威脅模型是合理的防護等級;真的要更強的話之後可以換成
    streamlit-authenticator 或放到有存取控制的內部網路後面。
    """
    expected = _configured_password()
    if not expected:
        st.error(
            "⚠ 尚未設定 DASHBOARD_PASSWORD,基於安全考量拒絕顯示任何資料。\n\n"
            "・本機執行:先 `export DASHBOARD_PASSWORD=你的密碼` 再啟動\n"
            '・Streamlit Community Cloud:App settings → Secrets 加入 '
            '`DASHBOARD_PASSWORD = "你的密碼"`'
        )
        st.stop()

    if st.session_state.get("authenticated"):
        return

    st.title("🔒 登入")
    password = st.text_input("密碼", type="password", key="password_input")
    if st.button("登入"):
        if hmac.compare_digest(password, expected):
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("密碼錯誤")
    st.stop()
