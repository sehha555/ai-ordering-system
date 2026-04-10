import re
import sqlite3
import json
import os
from contextlib import contextmanager
from datetime import datetime
from typing import List, Dict, Any, Optional

# 專案根目錄（order_repository.py → repository/ → src/ → project root）
_PROJECT_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))


class OrderRepository:
    def __init__(self, db_path: str = "orders.db"):
        self.db_path = db_path
        self._init_db()

    @contextmanager
    def _connection(self, *, immediate: bool = False):
        """連接 contextmanager — 自動 commit/rollback/close。immediate=True 使用 BEGIN IMMEDIATE。"""
        conn = sqlite3.connect(self.db_path, timeout=5)
        conn.row_factory = sqlite3.Row
        if immediate:
            conn.execute("BEGIN IMMEDIATE")
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
            # 索引優化：加速日期篩選、狀態查詢、會話查詢
            conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_created_at ON orders(created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_session_id ON orders(session_id)")

    def get_order(self, order_id: str) -> Optional[Dict[str, Any]]:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT order_payload_json FROM orders WHERE order_id = ?", (order_id,)
            ).fetchone()
            if row:
                return json.loads(row["order_payload_json"])
        return None

    def list_orders(
        self,
        date: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
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

    def update_status(self, order_id: str, status: str):
        """更新訂單狀態（DB status 欄位 + order_payload_json 內的 status）"""
        with self._connection() as conn:
            result = conn.execute(
                "UPDATE orders SET status = ?, order_payload_json = json_set(order_payload_json, '$.status', ?) WHERE order_id = ?",
                (status, status, order_id),
            )
            if result.rowcount == 0:
                raise ValueError(f"訂單不存在：{order_id}")

    def update_payment_status(self, order_id: str, payment_status: str):
        """更新 order_payload_json 內的 payment_status 欄位"""
        with self._connection() as conn:
            result = conn.execute(
                "UPDATE orders SET order_payload_json = json_set(order_payload_json, '$.payment_status', ?) WHERE order_id = ?",
                (payment_status, order_id),
            )
            if result.rowcount == 0:
                raise ValueError(f"訂單不存在：{order_id}")

    def save_order_with_number(self, order_payload: Dict[str, Any], session_id: str) -> str:
        """
        原子性取號 + 儲存訂單，避免 TOCTOU 競態。回傳 order_number。
        使用 BEGIN IMMEDIATE 確保取號和寫入在同一 exclusive transaction 內。
        """
        today = datetime.now().strftime("%Y-%m-%d")
        order_id = order_payload["order_id"]
        status = order_payload.get("status", "SUBMITTED")
        created_at = order_payload.get("created_at", datetime.now().isoformat())
        total_price = order_payload.get("total_price", 0)

        with self._connection(immediate=True) as conn:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM orders WHERE created_at LIKE ?",
                (f"{today}%",),
            ).fetchone()
            next_num = (row["cnt"] or 0) + 1
            order_number = f"{next_num:02d}"

            order_payload["order_number"] = order_number
            items_json = json.dumps(order_payload.get("items", []), ensure_ascii=False)
            payload_json = json.dumps(order_payload, ensure_ascii=False)

            conn.execute(
                """
                INSERT OR REPLACE INTO orders
                (order_id, status, created_at, session_id, items_json, total_price, order_payload_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
                (order_id, status, created_at, session_id, items_json, total_price, payload_json),
            )

        return order_number

    def save_conversation_log_json(
        self,
        session_id: str,
        order_number: str,
        cart: List[Dict],
        total: int,
        dine_type: str,
        messages: List[Dict[str, Any]],
        raw_messages: List[Dict[str, Any]] | None = None,
    ):
        """保存對話紀錄為 JSON 檔案

        raw_messages: LLM 原始輸出（含 [ADD:...] 等 text tags），訓練資料用。
                      messages 是 tag strip 後供 history 使用的清理版本。
        """
        today = datetime.now().strftime("%Y-%m-%d")
        # 使用絕對路徑，避免相對路徑依賴 CWD
        log_dir = os.path.join(_PROJECT_ROOT, "logs", today)
        os.makedirs(log_dir, exist_ok=True)

        # sanitize session_id，只允許英數字、連字符、底線，防止路徑穿越攻擊
        safe_id = re.sub(r"[^a-zA-Z0-9_-]", "", session_id)
        if not safe_id:
            safe_id = "unknown"

        log_data = {
            "session_id": session_id,
            "order_number": order_number,
            "cart": cart,
            "total": total,
            "dine_type": dine_type,
            "messages": messages,
            "raw_messages": raw_messages or [],
            "created_at": datetime.now().isoformat(),
        }

        log_file = os.path.join(log_dir, f"{safe_id}.json")
        with open(log_file, "w", encoding="utf-8") as f:
            json.dump(log_data, f, ensure_ascii=False, indent=2)


# 全域實例
order_repo = OrderRepository()
