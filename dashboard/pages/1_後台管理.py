"""後台管理儀表板(Streamlit,密碼保護)。

一個 repo、兩個獨立子專案共用同一個後台介面:
- 台股全能 AI 決策系統(taiwan_stock_ai/):事實表健康度、訊號瀏覽、LINE 查詢預覽
- DecisionRecord 平台(scripts/decision_writer.py):決策記錄瀏覽、統計圖表

跟 `dashboard/app.py`(前台,公開,顯示行情/K 線/訊號觀察清單)是刻意分開
的兩個頁面:前台給任何人看行情,後台顯示交易決策細節,只有你自己看得到。

**純唯讀**:這支程式完全不寫入任何資料庫。所有寫入還是走各自既有的路徑
(taiwan_stock_ai 的排程批次 / decision_writer.py CLI / GitHub Actions)——
儀表板只是多一個「看」的介面,不取代任何既有工作流程。

密碼保護:部署到 Streamlit Community Cloud 之類的公開託管後,前台網址預設
任何人都能打開,但這一頁會直接顯示交易決策細節——這牴觸了本專案反覆強調
的「不對外開放」原則。所以在畫出任何資料前,一律先過 `require_password()`
這關,而且刻意 fail-closed:沒設定密碼就直接拒絕顯示。設定方式見
`common.require_password()` 的說明與 `README_QUICK_START.md`「🖥 後台儀表板」
章節。
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import duckdb
import streamlit as st

# pages/ 底下的檔案跟主腳本(dashboard/app.py)不在同一個目錄,顯式加
# dashboard/ 進 sys.path 才能 import 到同一份 common.py,不依賴 Streamlit
# 對 sys.path 的預設行為。
_DASHBOARD_DIR = Path(__file__).resolve().parent.parent
if str(_DASHBOARD_DIR) not in sys.path:
    sys.path.insert(0, str(_DASHBOARD_DIR))

from common import (  # noqa: E402
    ADMIN_DISCLAIMER,
    DecisionWriter,
    DEFAULT_DB_PATH,
    require_password,
    ts_handle_query,
    ts_settings,
)

st.set_page_config(page_title="後台管理", page_icon="🔒", layout="wide")

require_password()

top_col, logout_col = st.columns([6, 1])
top_col.title("後台管理儀表板")
if logout_col.button("登出"):
    st.session_state["authenticated"] = False
    st.rerun()
st.caption(ADMIN_DISCLAIMER)

tab_stock, tab_decision = st.tabs(["📈 台股全能 AI 決策系統", "🧾 DecisionRecord 平台"])


# ---------------------------------------------------------------------------
# Tab 1:台股全能 AI 決策系統(DuckDB)
# ---------------------------------------------------------------------------
with tab_stock:
    st.subheader("資料來源")
    duckdb_path = st.text_input(
        "DuckDB 事實表路徑", value=ts_settings.duckdb_path, key="duckdb_path"
    )

    if not Path(duckdb_path).exists():
        st.info(
            "找不到資料庫檔案,尚未跑過每日批次。先執行:\n\n"
            "`python -m taiwan_stock_ai.scheduler.run_daily`"
        )
    else:
        try:
            # read_only=True:DuckDB 的檔案鎖是獨佔式的,寫入連線會擋掉其他
            # 任何連線(包含另一個 read_only 連線)。儀表板一律只讀,才不會
            # 跟排程批次的寫入連線互卡,也不會不小心在這裡誤寫資料。
            conn = duckdb.connect(duckdb_path, read_only=True)
        except duckdb.Error as exc:
            st.error(f"連線失敗(資料庫可能正被批次寫入中,稍後再試):{exc}")
            conn = None

        if conn is not None:
            try:
                stock_count, latest_date = conn.execute(
                    "SELECT COUNT(DISTINCT stock_id), MAX(trade_date) FROM daily_quotes"
                ).fetchone()
                signal_count_today = conn.execute(
                    "SELECT COUNT(*) FROM signals WHERE signal_date = "
                    "(SELECT MAX(signal_date) FROM signals)"
                ).fetchone()[0]
                recent_failures = conn.execute(
                    "SELECT COUNT(*) FROM fetch_log "
                    "WHERE status != 'success' AND fetch_date >= current_date - 7"
                ).fetchone()[0]

                col1, col2, col3, col4 = st.columns(4)
                col1.metric("事實表股票數", stock_count or 0)
                col2.metric("最新資料日期", str(latest_date) if latest_date else "—")
                col3.metric("最新一批訊號數", signal_count_today or 0)
                col4.metric("近 7 天抓取失敗次數", recent_failures or 0, delta_color="inverse")

                if recent_failures:
                    st.warning(f"近 7 天有 {recent_failures} 次資料抓取失敗,見下方 fetch_log。")

                st.subheader("抓取健康度(fetch_log,最近 20 筆)")
                fetch_log_rows = conn.execute(
                    "SELECT dataset, fetch_date, status, row_count, error_message, finished_at "
                    "FROM fetch_log ORDER BY fetch_date DESC, started_at DESC LIMIT 20"
                ).fetchall()
                fetch_log_cols = ["dataset", "fetch_date", "status", "row_count", "error_message", "finished_at"]
                st.dataframe(
                    [dict(zip(fetch_log_cols, row)) for row in fetch_log_rows],
                    width="stretch",
                )

                st.subheader("訊號瀏覽")
                signal_dates = [
                    r[0]
                    for r in conn.execute(
                        "SELECT DISTINCT signal_date FROM signals ORDER BY signal_date DESC LIMIT 30"
                    ).fetchall()
                ]
                if not signal_dates:
                    st.info("目前事實表裡還沒有任何訊號。")
                else:
                    selected_date = st.selectbox("日期", signal_dates, key="signal_date")
                    tag_filter = st.multiselect(
                        "標籤", ["當沖", "波段", "中長線"], default=["當沖", "波段", "中長線"]
                    )

                    base_query = (
                        "SELECT s.stock_id, q.stock_name, s.signal_name, s.tag, s.direction, "
                        "s.strength, s.description, s.excluded_reason "
                        "FROM signals s "
                        "LEFT JOIN daily_quotes q ON q.stock_id = s.stock_id AND q.trade_date = s.signal_date "
                        "WHERE s.signal_date = ?"
                    )
                    params: list[Any] = [selected_date]
                    if tag_filter:
                        placeholders = ",".join(["?"] * len(tag_filter))
                        base_query += f" AND s.tag IN ({placeholders})"
                        params.extend(tag_filter)

                    rows = conn.execute(base_query + " ORDER BY s.strength DESC", params).fetchall()
                    cols = [
                        "stock_id", "stock_name", "signal_name", "tag", "direction",
                        "strength", "description", "excluded_reason",
                    ]
                    st.dataframe([dict(zip(cols, r)) for r in rows], width="stretch")

                st.subheader("LINE 查詢預覽")
                st.caption("直接呼叫 LINE Bot 同一套規則引擎(0 token),預覽它會回什麼。")
                query_text = st.text_input(
                    "輸入股票代號(如 2330)或「今日當沖選股」", key="line_query_preview"
                )
                if query_text:
                    st.code(ts_handle_query(conn, query_text), language=None)
            finally:
                conn.close()


# ---------------------------------------------------------------------------
# Tab 2:DecisionRecord 平台(SQLite)
# ---------------------------------------------------------------------------
with tab_decision:
    st.subheader("資料來源")
    sqlite_path = st.text_input("SQLite 資料庫路徑", value=DEFAULT_DB_PATH, key="sqlite_path")

    if not Path(sqlite_path).exists():
        st.info(
            "找不到資料庫檔案,還沒記錄過任何決策。先用方案 1 記一筆:\n\n"
            "`python scripts/decision_writer.py --json \"$(python scripts/decision_writer.py --example)\"`"
        )
    else:
        try:
            writer = DecisionWriter(sqlite_path)
        except Exception as exc:  # noqa: BLE001 - 顯示給使用者看,不要整頁掛掉
            st.error(f"開啟資料庫失敗:{exc}")
            writer = None

        if writer is not None:
            try:
                stats = writer.get_stats()
                col1, col2, col3, col4, col5 = st.columns(5)
                col1.metric("總決策數", stats["total_decisions"])
                col2.metric("已回填", stats["completed"])
                col3.metric("待回填", stats["pending"])
                col4.metric(
                    "勝率", f"{stats['win_rate']:.1%}" if "win_rate" in stats else "—"
                )
                col5.metric(
                    "平均 R", f"{stats['avg_pnl_R']:+.2f}" if "avg_pnl_R" in stats else "—"
                )
                if stats.get("warning"):
                    st.caption(f"⚠ {stats['warning']}")

                st.subheader("決策清單(最新 500 筆)")
                decisions = writer.list_all(500)
                if not decisions:
                    st.info("目前還沒有任何決策記錄。")
                else:
                    summary_rows: list[dict[str, Any]] = []
                    for d in decisions:
                        trader_state = d.get("trader_state") or {}
                        reasoning_tags = (
                            trader_state.get("reasoning_tags", {})
                            if isinstance(trader_state, dict)
                            else {}
                        )
                        action = d.get("action") or {}
                        post_outcome = d.get("post_outcome") or {}
                        summary_rows.append(
                            {
                                "id": d.get("id"),
                                "ts": d.get("ts"),
                                "setup_type": reasoning_tags.get("setup_type") if isinstance(reasoning_tags, dict) else None,
                                "side": action.get("side") if isinstance(action, dict) else None,
                                "confidence": trader_state.get("confidence") if isinstance(trader_state, dict) else None,
                                "pnl_R": post_outcome.get("pnl_R") if isinstance(post_outcome, dict) else None,
                            }
                        )
                    st.dataframe(summary_rows, width="stretch")

                    st.subheader("已回填決策的 R 值分布")
                    pnl_values = [r["pnl_R"] for r in summary_rows if isinstance(r.get("pnl_R"), (int, float))]
                    if pnl_values:
                        st.bar_chart(pnl_values)
                    else:
                        st.caption("目前還沒有已回填 pnl_R 的決策,暫時沒有圖可畫。")

                    st.subheader("單筆詳情")
                    ids = [r["id"] for r in summary_rows]
                    selected_id = st.selectbox("選擇決策 ID", ids, key="decision_detail")
                    if selected_id:
                        st.json(writer.read_decision(selected_id))
            finally:
                writer.close()

st.divider()
st.caption(ADMIN_DISCLAIMER)
