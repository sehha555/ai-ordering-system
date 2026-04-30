"""
Pipeline 事件 SSE 廣播器

監聽 voice_router pipeline 各階段事件（ASR / LLM / Tag / Tool / Cart），
推送給 admin/monitor 頁面即時觀察。仿 OrderBroadcaster 設計：
asyncio.Queue + heartbeat + 慢速 client 丟棄事件。
"""

import asyncio
import json
import time
from typing import Any, AsyncIterator, Dict


class PipelineEventBroadcaster:
    def __init__(self):
        self._subscribers: set[asyncio.Queue] = set()

    async def subscribe(self) -> AsyncIterator[str]:
        """訂閱 SSE 事件流。30 秒無事件送 heartbeat，斷線自動清除。"""
        queue: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._subscribers.add(queue)
        try:
            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield f"event: pipeline\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
        except (asyncio.CancelledError, GeneratorExit):
            pass
        finally:
            self._subscribers.discard(queue)

    def emit(self, event_type: str, session_id: str, data: Dict[str, Any]) -> None:
        """同步推送事件給所有訂閱者。voice_router 在 hot path 呼叫，nowait 避免阻塞。"""
        if not self._subscribers:
            return
        payload = {
            "type": event_type,
            "session_id": session_id,
            "timestamp": time.time(),
            "data": data,
        }
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                pass


pipeline_broadcaster = PipelineEventBroadcaster()
