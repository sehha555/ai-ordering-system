import sqlite3
import json
import os
from datetime import datetime
from typing import List, Dict, Any, Optional

class OrderRepository:
    def __init__(self, db_path: str = "orders.db"):
        self.db_path = db_path
        self._init_db()

    def _get_connection(self):
        # 確保連線在 Windows 下能正確關閉
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        conn = self._get_connection()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS orders (
                    order_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    items_json TEXT NOT NULL,
                    total_price INTEGER NOT NULL,
                    order_payload_json TEXT NOT NULL
                )
            """)
            conn.commit()
        finally:
            conn.close()

    def save_order(self, order_payload: Dict[str, Any], session_id: str):
        order_id = order_payload["order_id"]
        status = order_payload.get("status", "SUBMITTED")
        created_at = order_payload.get("created_at", datetime.now().isoformat())
        items_json = json.dumps(order_payload.get("items", []), ensure_ascii=False)
        total_price = order_payload.get("total_price", 0)
        payload_json = json.dumps(order_payload, ensure_ascii=False)

        conn = self._get_connection()
        try:
            conn.execute("""
                INSERT OR REPLACE INTO orders 
                (order_id, status, created_at, session_id, items_json, total_price, order_payload_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (order_id, status, created_at, session_id, items_json, total_price, payload_json))
            conn.commit()
        finally:
            conn.close()

    def get_order(self, order_id: str) -> Optional[Dict[str, Any]]:
        conn = self._get_connection()
        try:
            row = conn.execute("SELECT order_payload_json FROM orders WHERE order_id = ?", (order_id,)).fetchone()
            if row:
                return json.loads(row["order_payload_json"])
        finally:
            conn.close()
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

        conn = self._get_connection()
        try:
            rows = conn.execute(query, params).fetchall()
            return [json.loads(r["order_payload_json"]) for r in rows]
        finally:
            conn.close()

# 全域實例
order_repo = OrderRepository()