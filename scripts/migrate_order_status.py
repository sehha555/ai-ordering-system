#!/usr/bin/env python3
"""
一次性 migration：修正 orders 表中不一致的 status 值。

執行方式：uv run python scripts/migrate_order_status.py
"""

import sqlite3
import os

DB_PATH = os.environ.get("DB_PATH", "orders.db")


def migrate():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        # 先查看現況
        rows = conn.execute("SELECT status, COUNT(*) as cnt FROM orders GROUP BY status").fetchall()
        print("遷移前 status 分佈：")
        for r in rows:
            print(f"  {r['status']!r}: {r['cnt']} 筆")

        # 修正 lowercase "submitted" → "SUBMITTED"
        # 修正 "SUCCESS" → "SUBMITTED"
        conn.execute("""
            UPDATE orders
            SET status = 'SUBMITTED',
                order_payload_json = json_set(order_payload_json, '$.status', 'SUBMITTED')
            WHERE status != 'SUBMITTED'
        """)
        affected = conn.total_changes
        conn.commit()

        rows_after = conn.execute(
            "SELECT status, COUNT(*) as cnt FROM orders GROUP BY status"
        ).fetchall()
        print(f"\n已更新 {affected} 筆")
        print("遷移後 status 分佈：")
        for r in rows_after:
            print(f"  {r['status']!r}: {r['cnt']} 筆")
    finally:
        conn.close()


if __name__ == "__main__":
    migrate()
