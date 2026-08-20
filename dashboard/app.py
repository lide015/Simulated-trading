"""台股全能 AI 決策系統 —— 前台(Streamlit,公開,無密碼)。

這是「給人看行情」的公開頁面:搜尋股票代號、紅漲綠跌報價、K 線圖、
今日訊號觀察清單。**完全不顯示 DecisionRecord(交易決策細節)**——那些
資料在後台(側欄「1 後台管理」,需要密碼),兩者刻意分開,不是漏做。

**純唯讀**:這支程式完全不寫入任何資料庫,所有寫入都走既有的排程批次/CLI/
GitHub Actions 路徑。

技術選型與範圍依據 docs/taiwan-stock-ai-blueprint.md「(c) Streamlit vs
Next.js+FastAPI」:MVP 階段先用 Streamlit 把資料視覺化跑出來,不必為了前台
另外養一套 Next.js。

啟動方式:
    streamlit run dashboard/app.py
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import altair as alt
import duckdb
import pandas as pd
import streamlit as st

# 明確把 dashboard/ 加進 sys.path 才 import common,不依賴 Streamlit 對主
# 腳本目錄的預設行為——這樣不管日後 common.py 被哪個 page 引用,行為都一致
# (見 pages/1_後台管理.py 的同樣寫法)。
_DASHBOARD_DIR = Path(__file__).resolve().parent
if str(_DASHBOARD_DIR) not in sys.path:
    sys.path.insert(0, str(_DASHBOARD_DIR))

from common import PUBLIC_DISCLAIMER, direction_color, ts_settings  # noqa: E402

st.set_page_config(page_title="台股全能 AI 決策系統", page_icon="📈", layout="wide")

st.title("📈 台股全能 AI 決策系統")
st.caption(PUBLIC_DISCLAIMER)


def _get_readonly_connection(duckdb_path: str) -> duckdb.DuckDBPyConnection | None:
    if not Path(duckdb_path).exists():
        return None
    try:
        # read_only=True:不跟排程批次的寫入連線互卡,前台也不該有能力寫資料。
        return duckdb.connect(duckdb_path, read_only=True)
    except duckdb.Error as exc:
        st.error(f"連線失敗(資料庫可能正被批次寫入中,稍後再試):{exc}")
        return None


def _render_candlestick(history: pd.DataFrame) -> None:
    """紅漲綠跌 K 線圖(Altair:蠟燭實體用 mark_bar,上下影線用 mark_rule)。"""
    history = history.copy()
    history["direction"] = history.apply(
        lambda r: "bullish" if r["close"] >= r["open"] else "bearish", axis=1
    )
    color_scale = alt.Scale(
        domain=["bullish", "bearish"],
        range=[direction_color("bullish"), direction_color("bearish")],
    )

    base = alt.Chart(history).encode(x=alt.X("trade_date:T", title="日期"))
    wicks = base.mark_rule().encode(
        y=alt.Y("low:Q", title="價格", scale=alt.Scale(zero=False)),
        y2="high:Q",
        color=alt.Color("direction:N", scale=color_scale, legend=None),
    )
    bodies = base.mark_bar(width=6).encode(
        y="open:Q",
        y2="close:Q",
        color=alt.Color("direction:N", scale=color_scale, legend=None),
        tooltip=[
            alt.Tooltip("trade_date:T", title="日期"),
            alt.Tooltip("open:Q", title="開盤"),
            alt.Tooltip("high:Q", title="最高"),
            alt.Tooltip("low:Q", title="最低"),
            alt.Tooltip("close:Q", title="收盤"),
            alt.Tooltip("volume_shares:Q", title="成交量"),
        ],
    )
    st.altair_chart((wicks + bodies).properties(height=420), width="stretch")


def _render_stock_search(conn: duckdb.DuckDBPyConnection) -> None:
    # GROUP BY + MAX(stock_name) 而非 SELECT DISTINCT:補歷史資料
    # (scheduler/backfill_history.py)來源是 FinMind,不一定每一列都有
    # 公司名稱,同一檔股票若有列 stock_name 是 NULL,DISTINCT 可能選到那筆
    # 讓下拉選單顯示空白名稱;MAX() 會優先挑到非 NULL 的值。
    all_stocks = conn.execute(
        "SELECT stock_id, MAX(stock_name) AS stock_name FROM daily_quotes "
        "GROUP BY stock_id ORDER BY stock_id"
    ).fetchall()
    if not all_stocks:
        st.info("事實表裡還沒有任何股票資料。")
        return

    options = {f"{sid} {name or ''}".strip(): sid for sid, name in all_stocks}
    label = st.selectbox("🔍 搜尋股票代號", options=list(options.keys()))
    stock_id = options[label]

    history_rows = conn.execute(
        """
        SELECT trade_date, stock_name, open, high, low, close, volume_shares, change
        FROM daily_quotes WHERE stock_id = ? ORDER BY trade_date DESC LIMIT 90
        """,
        [stock_id],
    ).fetchall()
    if not history_rows:
        st.info(f"{stock_id} 沒有歷史資料。")
        return

    cols = ["trade_date", "stock_name", "open", "high", "low", "close", "volume_shares", "change"]
    history = pd.DataFrame(history_rows, columns=cols).sort_values("trade_date")
    latest = history.iloc[-1]

    quote_color = direction_color("bullish" if (latest["change"] or 0) >= 0 else "bearish")
    st.markdown(
        f"### {stock_id} {latest['stock_name'] or ''} "
        f"<span style='color:{quote_color}'>{latest['close']:.2f}"
        f"({latest['change']:+.2f})</span>",
        unsafe_allow_html=True,
    )
    st.caption(f"最新交易日:{latest['trade_date']}")

    _render_candlestick(history)

    st.subheader("今日訊號")
    signal_rows = conn.execute(
        """
        SELECT tag, direction, description, excluded_reason
        FROM signals WHERE stock_id = ? AND signal_date = ?
        ORDER BY strength DESC
        """,
        [stock_id, latest["trade_date"]],
    ).fetchall()
    if not signal_rows:
        st.caption("今日無觸發訊號。")
    else:
        for tag, direction, description, excluded_reason in signal_rows:
            arrow = "▲" if direction == "bullish" else "▼"
            st.markdown(
                f"<span style='color:{direction_color(direction)}'>{arrow} [{tag}]</span> {description}",
                unsafe_allow_html=True,
            )
            if excluded_reason:
                st.caption(f"⚠ {excluded_reason}")


def _render_watchlist(conn: duckdb.DuckDBPyConnection) -> None:
    st.subheader("📋 今日訊號觀察清單")
    st.caption("規則引擎輸出,純描述性文字,不是買賣建議(當沖項目已排除處置股)。")

    latest_signal_date = conn.execute("SELECT MAX(signal_date) FROM signals").fetchone()[0]
    if latest_signal_date is None:
        st.info("目前事實表裡還沒有任何訊號。")
        return

    tag_filter = st.multiselect(
        "篩選標籤", ["當沖", "波段", "中長線"], default=["當沖", "波段", "中長線"], key="watchlist_tags"
    )
    params: list[Any] = [latest_signal_date]
    query = (
        "SELECT s.stock_id, q.stock_name, s.tag, s.direction, s.description "
        "FROM signals s "
        "LEFT JOIN daily_quotes q ON q.stock_id = s.stock_id AND q.trade_date = s.signal_date "
        "WHERE s.signal_date = ? AND s.excluded_reason IS NULL"
    )
    if tag_filter:
        placeholders = ",".join(["?"] * len(tag_filter))
        query += f" AND s.tag IN ({placeholders})"
        params.extend(tag_filter)
    rows = conn.execute(query + " ORDER BY s.strength DESC LIMIT 50", params).fetchall()

    if not rows:
        st.info(f"{latest_signal_date} 沒有符合篩選條件的訊號。")
        return

    st.caption(f"訊號日期:{latest_signal_date}")
    display_rows = [
        {
            "股票代號": stock_id,
            "名稱": stock_name,
            "標籤": tag,
            "方向": "▲ 漲" if direction == "bullish" else "▼ 跌",
            "說明": description,
        }
        for stock_id, stock_name, tag, direction, description in rows
    ]
    st.dataframe(display_rows, width="stretch")


duckdb_path = ts_settings.duckdb_path
conn = _get_readonly_connection(duckdb_path)

if conn is None:
    st.info(
        "尚未有任何資料,批次還沒跑過。開發者需要先執行:\n\n"
        "`python -m taiwan_stock_ai.scheduler.run_daily`"
    )
else:
    try:
        _render_stock_search(conn)
        st.divider()
        _render_watchlist(conn)
    finally:
        conn.close()

st.divider()
st.caption(PUBLIC_DISCLAIMER)
