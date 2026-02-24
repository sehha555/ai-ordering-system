# src/repository/conversation_log.py
"""對話紀錄持久化 — 供分析與微調用"""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Dict, Any, List, Optional

from loguru import logger


class ConversationLog:
    def __init__(self, db_path: str = "orders.db"):
        self.db_path = db_path
        self._init_db()

    @contextmanager
    def _connection(self):
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
                CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    messages TEXT NOT NULL,
                    metadata TEXT,
                    started_at TEXT,
                    ended_at TEXT NOT NULL,
                    created_at TEXT DEFAULT (datetime('now', 'localtime'))
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_conv_session ON conversations(session_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_conv_ended ON conversations(ended_at)")

    def save(self, session_id: str, session_data: Dict[str, Any]) -> None:
        """儲存一段完整對話"""
        history = session_data.get("history", [])
        if not history:
            return  # 沒有對話歷史就不存

        cart = session_data.get("cart", [])
        metadata = {
            "turns": len(history),
            "items_count": len(cart),
            "completed": session_data.get("status") == "SUBMITTED",
        }

        now = datetime.now().isoformat()
        started_at = session_data.get("started_at", now)

        try:
            with self._connection() as conn:
                conn.execute(
                    "INSERT INTO conversations (session_id, messages, metadata, started_at, ended_at) VALUES (?, ?, ?, ?, ?)",
                    (
                        session_id,
                        json.dumps(history, ensure_ascii=False),
                        json.dumps(metadata, ensure_ascii=False),
                        started_at,
                        now,
                    ),
                )
            logger.info("對話紀錄已儲存: session={}, turns={}", session_id, len(history))
        except Exception as e:
            logger.warning("對話紀錄儲存失敗 ({}): {}", session_id, e)

    def list_conversations(self, date: Optional[str] = None, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        """列出對話紀錄"""
        with self._connection() as conn:
            if date:
                rows = conn.execute(
                    "SELECT * FROM conversations WHERE ended_at LIKE ? ORDER BY ended_at DESC LIMIT ? OFFSET ?",
                    (f"{date}%", limit, offset),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM conversations ORDER BY ended_at DESC LIMIT ? OFFSET ?",
                    (limit, offset),
                ).fetchall()
            return [dict(row) for row in rows]

    def get_by_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """取得特定 session 的對話紀錄"""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM conversations WHERE session_id = ? ORDER BY ended_at DESC LIMIT 1",
                (session_id,),
            ).fetchone()
            return dict(row) if row else None


conversation_log = ConversationLog()
