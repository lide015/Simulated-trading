#!/usr/bin/env python3
"""DecisionRecord CLI + 函式庫。

對應 README.md 「3. 核心資料結構」與「3.4 三張資料表」的規格,是
docs/CLAUDE_INTEGRATION.md 方案 1(Copy-Paste JSON)背後的實作:Claude 產生
DecisionRecord JSON,你在本機執行這支程式把它寫進 SQLite;方案 2(GitHub
Actions)、方案 3(FastAPI,見 api_server.py)也都是呼叫這裡的
`DecisionWriter` / `create_decision_from_dict`,不是各自重寫一份邏輯。
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "db" / "schema.sql"
DEFAULT_DB_PATH = os.getenv("DATABASE_PATH", str(REPO_ROOT / "trading.db"))

REQUIRED_KEYS = ("market_snapshot", "trader_state", "action")


@dataclass
class DecisionRecord:
    id: str
    ts: str
    market_snapshot: dict[str, Any]
    trader_state: dict[str, Any]
    action: dict[str, Any]
    post_outcome: Optional[dict[str, Any]] = None


def create_decision_from_dict(payload: dict[str, Any]) -> DecisionRecord:
    """把 Claude 產生的 dict 轉成 DecisionRecord,缺 id/ts 就自動補上。"""
    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object")

    missing = [k for k in REQUIRED_KEYS if k not in payload]
    if missing:
        raise ValueError(f"payload missing required keys: {', '.join(missing)}")

    return DecisionRecord(
        id=payload.get("id") or f"dec-{uuid.uuid4().hex[:12]}",
        ts=payload.get("ts") or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        market_snapshot=payload["market_snapshot"],
        trader_state=payload["trader_state"],
        action=payload["action"],
        post_outcome=payload.get("post_outcome"),
    )


class DecisionWriter:
    """管理 SQLite(`decisions` / `experiments` / `discovery_log`)的讀寫。

    CLI 每次呼叫都是「開連線 → 做一件事 → 關連線」的短生命週期,天生沒有
    跨執行緒問題。但 api_server.py 是長駐行程,FastAPI 會把同步的 endpoint
    丟到 threadpool 執行,同一個 DecisionWriter 實例可能被不同執行緒呼叫
    ——所以這裡用 `check_same_thread=False` + `threading.Lock` 把每次存取都
    序列化,犧牲一點併發效能換正確性,對個人工具的流量來說完全足夠。
    """

    def __init__(self, db_path: str = DEFAULT_DB_PATH) -> None:
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._init_schema()

    def _init_schema(self) -> None:
        if SCHEMA_PATH.exists():
            with self._lock:
                self.conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
                self.conn.commit()

    def write_decision(self, record: DecisionRecord) -> bool:
        """寫入一筆新決策。

        已存在的 id 會被拒絕、不覆蓋——README.md 9.2「反模式」明確禁止
        「給自己補登的後門」,決策一旦寫入就該視為鎖定。
        """
        with self._lock:
            existing = self.conn.execute(
                "SELECT 1 FROM decisions WHERE id = ?", (record.id,)
            ).fetchone()
            if existing:
                print(f"⚠ 決策 {record.id} 已存在,拒絕覆蓋(避免事後改資料)", file=sys.stderr)
                return False

            self.conn.execute(
                """
                INSERT INTO decisions (id, ts, market_snapshot, trader_state, action, post_outcome, is_locked)
                VALUES (?, ?, ?, ?, ?, ?, 1)
                """,
                (
                    record.id,
                    record.ts,
                    json.dumps(record.market_snapshot, ensure_ascii=False),
                    json.dumps(record.trader_state, ensure_ascii=False),
                    json.dumps(record.action, ensure_ascii=False),
                    json.dumps(record.post_outcome, ensure_ascii=False) if record.post_outcome else None,
                ),
            )
            self.conn.commit()
            return True

    def read_decision(self, decision_id: str) -> Optional[dict[str, Any]]:
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM decisions WHERE id = ?", (decision_id,)
            ).fetchone()
        return _row_to_dict(row) if row is not None else None

    def list_completed(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM decisions WHERE post_outcome IS NOT NULL ORDER BY ts DESC"
            ).fetchall()
        return [_row_to_dict(r) for r in rows]

    def get_stats(self) -> dict[str, Any]:
        with self._lock:
            total = self.conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0]
            completed = self.conn.execute(
                "SELECT COUNT(*) FROM decisions WHERE post_outcome IS NOT NULL"
            ).fetchone()[0]
            raw_outcomes = self.conn.execute(
                "SELECT post_outcome FROM decisions WHERE post_outcome IS NOT NULL"
            ).fetchall()

        pnl_values: list[float] = []
        for (raw,) in raw_outcomes:
            try:
                outcome = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(outcome, dict) and "pnl_R" in outcome:
                try:
                    pnl_values.append(float(outcome["pnl_R"]))
                except (TypeError, ValueError):
                    continue

        stats: dict[str, Any] = {
            "total_decisions": total,
            "completed": completed,
            "pending": total - completed,
        }
        if pnl_values:
            wins = sum(1 for v in pnl_values if v > 0)
            stats["win_rate"] = round(wins / len(pnl_values), 4)
            stats["avg_pnl_R"] = round(sum(pnl_values) / len(pnl_values), 4)
            stats["n_with_pnl"] = len(pnl_values)
            if len(pnl_values) < 20:
                stats["warning"] = "n<20,統計量還不穩定(見 README.md 9.2 反模式)"
        return stats

    def close(self) -> None:
        with self._lock:
            self.conn.close()

    def __enter__(self) -> "DecisionWriter":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    for key in ("market_snapshot", "trader_state", "action", "post_outcome"):
        if result.get(key):
            try:
                result[key] = json.loads(result[key])
            except (json.JSONDecodeError, TypeError):
                pass
    result["is_locked"] = bool(result.get("is_locked"))
    return result


EXAMPLE_DECISION: dict[str, Any] = {
    "id": "dec-2026-08-15-example-001",
    "ts": "2026-08-15T14:30:00Z",
    "market_snapshot": {
        "price": 73850,
        "indicators": {"1h": {"rsi": 68, "atr": 420, "macd_hist": 12.3}},
        "funding_rate": 0.00012,
        "session": "asia",
    },
    "trader_state": {
        "prediction_text": "預期從 73000 支撐反彈",
        "confidence": 4,
        "reasoning_tags": {
            "setup_type": "mean_reversion",
            "key_level": "round_number",
            "indicator_trigger": ["rsi_overbought_1h"],
            "market_regime": "ranging",
        },
        "emotion": "calm",
    },
    "action": {
        "side": "long",
        "size": 0.05,
        "entry": 73850,
        "sl": 72900,
        "tp": 75500,
        "risk_amount": 100,
        "sl_distance_R": 1.0,
        "tp_distance_R": 1.74,
    },
}


def _print_json(obj: Any) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="DecisionRecord CLI(見 docs/CLAUDE_INTEGRATION.md 方案 1)"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--example", action="store_true", help="印出範例 DecisionRecord JSON")
    group.add_argument("--json", metavar="JSON", help="把這筆 JSON 寫入資料庫")
    group.add_argument("--stats", action="store_true", help="顯示統計資訊")
    group.add_argument("--list", action="store_true", help="列出已回填 outcome 的決策")
    group.add_argument("--read", metavar="ID", help="讀取單筆決策")
    parser.add_argument(
        "--db", default=DEFAULT_DB_PATH, help="資料庫路徑(預設讀 DATABASE_PATH 環境變數)"
    )
    args = parser.parse_args(argv)

    if args.example:
        _print_json(EXAMPLE_DECISION)
        return 0

    with DecisionWriter(args.db) as writer:
        if args.json is not None:
            try:
                payload = json.loads(args.json)
            except json.JSONDecodeError as exc:
                print(f"❌ JSON 解析失敗: {exc}", file=sys.stderr)
                return 1
            try:
                record = create_decision_from_dict(payload)
            except ValueError as exc:
                print(f"❌ {exc}", file=sys.stderr)
                return 1
            if writer.write_decision(record):
                print(f"✅ 決策已記錄: {record.id}")
                return 0
            return 1

        if args.stats:
            _print_json(writer.get_stats())
            return 0

        if args.list:
            _print_json(writer.list_completed())
            return 0

        if args.read:
            record = writer.read_decision(args.read)
            if record is None:
                print(f"查無決策: {args.read}", file=sys.stderr)
                return 1
            _print_json(record)
            return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
