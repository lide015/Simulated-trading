"""模板句庫(0 token)。

LINE Bot 的每一句回覆都從這裡的字串模板組出來,不呼叫任何 LLM——這是
報告反覆強調、必須堅守的「規則引擎＋模板句庫為主」底線。所有句子都是
**描述性**語言(「出現量增價漲」),不是**結果預測/推介性**語言
(「建議買進」),對應報告 9.1「壞標籤 5 問」與法遵章節的紅線。
"""
from __future__ import annotations

import datetime as dt
from typing import Any

DISCLAIMER = "⚠ 本查詢僅供個人研究參考,非投資建議,請自行判斷風險。"

HELP_TEXT = (
    "可用指令:\n"
    "・輸入股票代號(如 2330)查詢最新訊號\n"
    "・輸入「今日當沖選股」查詢當日候選清單\n\n" + DISCLAIMER
)


def render_help() -> str:
    return HELP_TEXT


def render_not_found(stock_id: str) -> str:
    return f"查無「{stock_id}」的最新資料,可能今天沒有收盤資料或代號有誤。\n\n{DISCLAIMER}"


def render_stock_signals(
    stock_id: str,
    quote: dict[str, Any] | None,
    signals: list[dict[str, Any]],
) -> str:
    lines: list[str] = []
    if quote:
        name = quote.get("stock_name") or ""
        close = quote.get("close")
        change = quote.get("change")
        trade_date = quote.get("trade_date")
        change_str = f"{change:+.2f}" if change is not None else "N/A"
        close_str = f"{close:.2f}" if close is not None else "N/A"
        lines.append(f"【{stock_id} {name}】{trade_date}")
        lines.append(f"收盤 {close_str}(漲跌 {change_str})")
    else:
        lines.append(f"【{stock_id}】(查無今日收盤資料)")

    if not signals:
        lines.append("今日無觸發訊號。")
    else:
        lines.append("")
        lines.append("觸發訊號:")
        for sig in signals:
            arrow = "▲" if sig.get("direction") == "bullish" else "▼"
            tag = sig.get("tag")
            desc = sig.get("description")
            excluded = sig.get("excluded_reason")
            line = f"[{tag}] {arrow} {desc}"
            if excluded:
                line += f"\n   ⚠ {excluded}"
            lines.append(line)

    lines.append("")
    lines.append(DISCLAIMER)
    return "\n".join(lines)


def render_day_trade_list(signal_date: dt.date, rows: list[dict[str, Any]]) -> str:
    header = f"{signal_date} 當沖候選觀察清單(依規則引擎，已排除處置股)"
    if not rows:
        return f"{header}\n\n今日無符合條件的候選。\n\n{DISCLAIMER}"

    lines = [header, ""]
    for row in rows:
        arrow = "▲" if row.get("direction") == "bullish" else "▼"
        stock_id = row.get("stock_id")
        stock_name = row.get("stock_name") or ""
        desc = row.get("description")
        lines.append(f"{arrow} {stock_id} {stock_name}\n   {desc}")

    lines.append("")
    lines.append(f"共 {len(rows)} 檔。{DISCLAIMER}")
    return "\n".join(lines)
