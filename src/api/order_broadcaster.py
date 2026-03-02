"""
訂單 SSE 廣播器 + 格式轉換

維護一組 asyncio.Queue，新訂單透過 broadcast() 推送到所有訂閱者。
format_order_for_admin() 放在此處避免 api ↔ dm 循環依賴。
"""

import asyncio
import json
from typing import AsyncIterator


def format_order_for_admin(raw: dict) -> dict:
    """將 DB 內的 order_payload 轉換為前端期望的格式。"""
    items = [
        {
            "name": item.get("name", ""),
            "price": item.get("unit_price", 0),
            "quantity": item.get("quantity", 1),
        }
        for item in raw.get("items_display", [])
    ]

    return {
        "order_id": raw.get("order_id", ""),
        "order_number": raw.get("order_number", ""),
        "status": raw.get("status", "SUBMITTED").upper(),
        "payment_status": raw.get("payment_status", "UNPAID"),
        "items": items,
        "total_price": raw.get("total_price", 0),
        "dine_type": raw.get("dine_type", ""),
        "created_at": raw.get("created_at", ""),
    }


class OrderBroadcaster:
    def __init__(self):
        self._subscribers: set[asyncio.Queue] = set()

    async def subscribe(self) -> AsyncIterator[str]:
        """訂閱 SSE 事件流。30 秒無事件送 heartbeat，斷線自動清除。"""
        queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._subscribers.add(queue)
        try:
            while True:
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield f"event: new_order\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
        except (asyncio.CancelledError, GeneratorExit):
            pass
        finally:
            self._subscribers.discard(queue)

    async def broadcast(self, order: dict):
        """推送訂單到所有訂閱者。慢速 client 丟棄事件。"""
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(order)
            except asyncio.QueueFull:
                pass


# 全域實例
order_broadcaster = OrderBroadcaster()
