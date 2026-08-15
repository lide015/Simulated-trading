#!/usr/bin/env python3
"""
Decision Record Writer for Simulated Trading Platform
======================================================

允許 Claude 或你自己直接寫入 DecisionRecord 到 SQLite 資料庫。

使用方式:
  1. 設定環境變數或傳參: DATABASE_PATH (default: ./trading.db)
  2. Python 直接呼叫: python scripts/decision_writer.py --json '{"id":"...", ...}'
  3. Claude 調用: 提供 JSON payload,系統自動驗證並寫入

Author: Lide × Claude
Version: 0.1 (MVP)
"""

import sqlite3
import json
import sys
import argparse
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict
from enum import Enum


# ============================================================================
# 資料結構定義 (基於 README 規格)
# ============================================================================

class SetupType(Enum):
    MEAN_REVERSION = "mean_reversion"
    TREND_CONTINUATION = "trend_continuation"
    RANGE_PLAY = "range_play"
    BREAKOUT = "breakout"
    BREAKOUT_RETEST = "breakout_retest"


class MarketRegime(Enum):
    RANGING = "ranging"
    TRENDING_UP = "trending_up"
    TRENDING_DOWN = "trending_down"
    PRE_BREAKOUT = "pre_breakout"
    POST_BREAKOUT = "post_breakout"


class ConfidenceLevel(Enum):
    VERY_LOW = 1
    LOW = 2
    MEDIUM = 3
    HIGH = 4
    VERY_HIGH = 5


class TraderEmotion(Enum):
    CALM = "calm"
    ANXIOUS = "anxious"
    FOMO = "fomo"
    REVENGE = "revenge"


@dataclass
class MarketSnapshot:
    """下單瞬間的市場快照 (來自 L1+L2)"""
    price: float
    ohlcv_multi_tf: Dict[str, List]  # {"15m": [...], "1h": [...], ...}
    indicators: Dict[str, Dict[str, float]]  # {"1h": {"rsi": 68, "atr": 420}, ...}
    orderbook_depth: Optional[Dict] = None
    funding_rate: Optional[float] = None
    session: Optional[str] = None  # auto-inferred: asia/eu/us
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class TraderState:
    """交易者的主觀判斷 (事前必填,事後鎖定)"""
    prediction_text: str  # 自然語言預測,如 "預期回測 73000 後反彈"
    confidence: ConfidenceLevel  # 1-5
    reasoning_tags: Dict[str, Any]  # 6維標籤體系
    emotion: Optional[TraderEmotion] = None
    
    def to_dict(self) -> Dict:
        return {
            "prediction_text": self.prediction_text,
            "confidence": self.confidence.value,
            "reasoning_tags": self.reasoning_tags,
            "emotion": self.emotion.value if self.emotion else None,
        }


@dataclass
class Action:
    """下單動作 (來自 L3 訂單模擬引擎)"""
    side: str  # "long" or "short"
    size: float  # BTC / ETH 數量
    entry: float  # 成交價
    sl: float  # stop loss
    tp: float  # take profit
    risk_amount: float  # USDT,1R 的具體值
    sl_distance_R: float  # 1R (通常 = abs(entry - sl) / entry * initial_capital)
    tp_distance_R: float  # 預期回報的 R 倍數
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class PostOutcome:
    """24h 後系統自動回填的結果 (事後鎖定,不可改)"""
    filled_at: Optional[str] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None  # tp_hit | sl_hit | timeout | manual
    pnl_R: Optional[float] = None
    pct_change: Optional[float] = None
    prediction_correct: Optional[bool] = None
    price_after_24h: Optional[float] = None
    max_favorable_excursion_R: Optional[float] = None
    max_adverse_excursion_R: Optional[float] = None
    
    def to_dict(self) -> Dict:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class DecisionRecord:
    """完整的決策記錄 (平台心臟)"""
    id: str  # UUID
    ts: str  # ISO 8601 UTC
    market_snapshot: MarketSnapshot
    trader_state: TraderState
    action: Action
    post_outcome: Optional[PostOutcome] = None
    
    def to_json_dict(self) -> Dict:
        """轉換為 JSON-ready 格式"""
        return {
            "id": self.id,
            "ts": self.ts,
            "market_snapshot": self.market_snapshot.to_dict(),
            "trader_state": self.trader_state.to_dict(),
            "action": self.action.to_dict(),
            "post_outcome": self.post_outcome.to_dict() if self.post_outcome else None,
        }


# ============================================================================
# 資料庫操作
# ============================================================================

class DecisionWriter:
    """SQLite 資料庫寫入器"""
    
    def __init__(self, db_path: str = "./trading.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
    
    def _init_db(self):
        """初始化資料庫 schema"""
        schema_path = Path(__file__).parent.parent / "db" / "schema.sql"
        if not schema_path.exists():
            print(f"⚠️  Warning: schema.sql not found at {schema_path}")
            print("Creating minimal schema...")
            self._create_minimal_schema()
        else:
            with open(schema_path, "r") as f:
                schema_sql = f.read()
            conn = sqlite3.connect(self.db_path)
            conn.executescript(schema_sql)
            conn.commit()
            conn.close()
            print(f"✅ Database initialized at {self.db_path}")
    
    def _create_minimal_schema(self):
        """最小 schema (若 schema.sql 不存在)"""
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS decisions (
                id TEXT PRIMARY KEY,
                ts TEXT NOT NULL,
                market_snapshot JSON NOT NULL,
                trader_state JSON NOT NULL,
                action JSON NOT NULL,
                post_outcome JSON DEFAULT NULL,
                is_locked BOOLEAN DEFAULT TRUE,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        conn.close()
    
    def write_decision(self, record: DecisionRecord) -> bool:
        """寫入一筆決策記錄"""
        try:
            conn = sqlite3.connect(self.db_path)
            record_json = record.to_json_dict()
            
            conn.execute(
                """
                INSERT INTO decisions 
                (id, ts, market_snapshot, trader_state, action, post_outcome, is_locked)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.ts,
                    json.dumps(record_json["market_snapshot"]),
                    json.dumps(record_json["trader_state"]),
                    json.dumps(record_json["action"]),
                    json.dumps(record_json["post_outcome"]) if record_json["post_outcome"] else None,
                    True,  # 事前必填,立即鎖定
                )
            )
            conn.commit()
            conn.close()
            
            print(f"✅ Decision saved: {record.id}")
            print(f"   Entry: {record.action.entry} ({record.action.side})")
            print(f"   Setup: {record.trader_state.reasoning_tags.get('setup_type', '?')}")
            return True
        
        except Exception as e:
            print(f"❌ Error writing decision: {e}")
            return False
    
    def read_decision(self, decision_id: str) -> Optional[Dict]:
        """讀取一筆記錄"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.execute("SELECT * FROM decisions WHERE id = ?", (decision_id,))
        row = cur.fetchone()
        conn.close()
        
        if row:
            return dict(row)
        return None
    
    def list_completed_decisions(self, limit: int = 10) -> List[Dict]:
        """列出已完成的決策 (已回填 post_outcome)"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            "SELECT id, ts, action, post_outcome FROM decisions WHERE post_outcome IS NOT NULL ORDER BY ts DESC LIMIT ?",
            (limit,)
        )
        rows = cur.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    
    def get_stats(self) -> Dict:
        """獲取統計資訊"""
        conn = sqlite3.connect(self.db_path)
        stats = {}
        
        # 總筆數
        count = conn.execute("SELECT COUNT(*) as n FROM decisions").fetchone()[0]
        stats["total_decisions"] = count
        
        # 已完成
        completed = conn.execute("SELECT COUNT(*) as n FROM decisions WHERE post_outcome IS NOT NULL").fetchone()[0]
        stats["completed_decisions"] = completed
        
        # 等待回填
        pending = count - completed
        stats["pending_decisions"] = pending
        
        conn.close()
        return stats


# ============================================================================
# CLI 介面
# ============================================================================

def parse_json_input(json_str: str) -> Dict:
    """解析 JSON 輸入"""
    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        print(f"❌ Invalid JSON: {e}")
        sys.exit(1)


def create_decision_from_dict(data: Dict) -> DecisionRecord:
    """從 dict 構造 DecisionRecord"""
    try:
        # 簡化版:假設輸入已經是正確格式
        # TODO: 添加完整驗證邏輯
        
        record = DecisionRecord(
            id=data.get("id") or str(uuid.uuid4()),
            ts=data.get("ts") or datetime.now(timezone.utc).isoformat(),
            market_snapshot=MarketSnapshot(
                price=data["market_snapshot"]["price"],
                ohlcv_multi_tf=data["market_snapshot"]["ohlcv_multi_tf"],
                indicators=data["market_snapshot"]["indicators"],
                funding_rate=data["market_snapshot"].get("funding_rate"),
                session=data["market_snapshot"].get("session"),
            ),
            trader_state=TraderState(
                prediction_text=data["trader_state"]["prediction_text"],
                confidence=ConfidenceLevel(data["trader_state"]["confidence"]),
                reasoning_tags=data["trader_state"]["reasoning_tags"],
                emotion=TraderEmotion(data["trader_state"]["emotion"]) if data["trader_state"].get("emotion") else None,
            ),
            action=Action(
                side=data["action"]["side"],
                size=data["action"]["size"],
                entry=data["action"]["entry"],
                sl=data["action"]["sl"],
                tp=data["action"]["tp"],
                risk_amount=data["action"]["risk_amount"],
                sl_distance_R=data["action"]["sl_distance_R"],
                tp_distance_R=data["action"]["tp_distance_R"],
            ),
        )
        return record
    
    except KeyError as e:
        print(f"❌ Missing required field: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error creating record: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Write DecisionRecord to SQLite database"
    )
    parser.add_argument(
        "--json",
        type=str,
        help="JSON payload (DecisionRecord)",
        required=False,
    )
    parser.add_argument(
        "--db",
        type=str,
        default="./trading.db",
        help="Database path (default: ./trading.db)",
    )
    parser.add_argument(
        "--read",
        type=str,
        help="Read a decision by ID",
        required=False,
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List completed decisions",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Show database statistics",
    )
    parser.add_argument(
        "--example",
        action="store_true",
        help="Print example JSON payload",
    )
    
    args = parser.parse_args()
    
    writer = DecisionWriter(args.db)
    
    # 顯示示例
    if args.example:
        example = {
            "id": "dec-2026-05-23-001",
            "ts": "2026-05-23T09:30:00Z",
            "market_snapshot": {
                "price": 73850,
                "ohlcv_multi_tf": {
                    "15m": [[1558608000, 73800, 73900, 73750, 73850, 100]],
                    "1h": [[1558608000, 73800, 73900, 73750, 73850, 100]],
                    "4h": [[1558608000, 73800, 73900, 73750, 73850, 100]],
                    "1d": [[1558608000, 73800, 73900, 73750, 73850, 100]],
                },
                "indicators": {
                    "1h": {"rsi": 68, "atr": 420, "macd_hist": 12.3},
                    "4h": {"rsi": 55, "atr": 980},
                },
                "funding_rate": 0.012,
                "session": "asia",
            },
            "trader_state": {
                "prediction_text": "預期回測 73000 後反彈",
                "confidence": 4,
                "reasoning_tags": {
                    "setup_type": "mean_reversion",
                    "key_level": "round_number",
                    "indicator_trigger": ["rsi_oversold_1h"],
                    "trader_emotion": "calm",
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
        print(json.dumps(example, indent=2, ensure_ascii=False))
        return
    
    # 顯示統計
    if args.stats:
        stats = writer.get_stats()
        print("\n📊 Database Statistics:")
        print(f"  Total decisions: {stats['total_decisions']}")
        print(f"  Completed: {stats['completed_decisions']}")
        print(f"  Pending: {stats['pending_decisions']}")
        return
    
    # 列出已完成的決策
    if args.list:
        records = writer.list_completed_decisions()
        print(f"\n📋 Completed Decisions ({len(records)}):")
        for rec in records:
            print(f"  {rec['id']}: {rec['ts']}")
        return
    
    # 讀取單筆記錄
    if args.read:
        record = writer.read_decision(args.read)
        if record:
            print(f"\n📌 Decision: {args.read}")
            # 格式化輸出
            print(json.dumps(dict(record), indent=2, ensure_ascii=False))
        else:
            print(f"❌ Decision not found: {args.read}")
        return
    
    # 寫入新記錄
    if args.json:
        data = parse_json_input(args.json)
        record = create_decision_from_dict(data)
        writer.write_decision(record)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
