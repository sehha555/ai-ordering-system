import sqlite3
import json
import os
from contextlib import contextmanager
from datetime import datetime
from typing import List, Dict, Any, Optional

class OrderRepository:
    def __init__(self, db_path: str = "orders.db"):
        self.db_path = db_path
        self._init_db()

    @contextmanager
    def _connection(self):
        """連接 contextmanager — 自動 commit/rollback/close"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self):
        with self._connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS orders (
                    order_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    items_json TEXT NOT NULL,
                    total_price INTEGER NOT NULL,
                    order_payload_json TEXT NOT NULL,
                    order_number TEXT,
                    dine_type TEXT,
                    payment_method TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS conversation_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    order_number TEXT,
                    messages TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # 索引優化：加速日期篩選、狀態查詢、會話查詢
            conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_created_at ON orders(created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_session_id ON orders(session_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_convlogs_session_id ON conversation_logs(session_id)")

    def save_order(self, order_payload: Dict[str, Any], session_id: str):
        order_id = order_payload["order_id"]
        status = order_payload.get("status", "SUBMITTED")
        created_at = order_payload.get("created_at", datetime.now().isoformat())
        items_json = json.dumps(order_payload.get("items", []), ensure_ascii=False)
        total_price = order_payload.get("total_price", 0)
        payload_json = json.dumps(order_payload, ensure_ascii=False)

        with self._connection() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO orders
                (order_id, status, created_at, session_id, items_json, total_price, order_payload_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (order_id, status, created_at, session_id, items_json, total_price, payload_json))

    def get_order(self, order_id: str) -> Optional[Dict[str, Any]]:
        with self._connection() as conn:
            row = conn.execute("SELECT order_payload_json FROM orders WHERE order_id = ?", (order_id,)).fetchone()
            if row:
                return json.loads(row["order_payload_json"])
        return None

    def list_orders(self, date: Optional[str] = None, status: Optional[str] = None, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        query = "SELECT order_payload_json FROM orders WHERE 1=1"
        params = []
        if date:
            query += " AND created_at LIKE ?"
            params.append(f"{date}%")
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([min(limit, 100), offset])

        with self._connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [json.loads(r["order_payload_json"]) for r in rows]

    def get_next_order_number(self) -> str:
        """
        獲取今天的下一個取餐號碼
        規則：每日 00:00 重置回 01，最少兩位補零（01, 02, ... 99, 100）
        使用 BEGIN IMMEDIATE 避免競態條件
        """
        today = datetime.now().strftime("%Y-%m-%d")
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("""
                SELECT COUNT(*) as cnt FROM orders WHERE created_at LIKE ?
            """, (f"{today}%",)).fetchone()
            next_num = (row["cnt"] or 0) + 1
            return f"{next_num:02d}"

    def save_conversation_log(self, session_id: str, order_number: str, messages: List[Dict[str, Any]]):
        """保存對話紀錄到 SQLite"""
        with self._connection() as conn:
            messages_json = json.dumps(messages, ensure_ascii=False)
            conn.execute("""
                INSERT INTO conversation_logs (session_id, order_number, messages)
                VALUES (?, ?, ?)
            """, (session_id, order_number, messages_json))

    def save_conversation_log_json(self, session_id: str, order_number: str, cart: List[Dict], total: int, dine_type: str, messages: List[Dict[str, Any]]):
        """保存對話紀錄為 JSON 檔案"""
        today = datetime.now().strftime("%Y-%m-%d")
        log_dir = os.path.join("logs", today)
        os.makedirs(log_dir, exist_ok=True)

        log_data = {
            "session_id": session_id,
            "order_number": order_number,
            "cart": cart,
            "total": total,
            "dine_type": dine_type,
            "messages": messages,
            "created_at": datetime.now().isoformat()
        }

        log_file = os.path.join(log_dir, f"{session_id}.json")
        with open(log_file, "w", encoding="utf-8") as f:
            json.dump(log_data, f, ensure_ascii=False, indent=2)

# 全域實例
order_repo = OrderRepository()
