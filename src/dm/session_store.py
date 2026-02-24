import time
from typing import Dict, Any, Optional, Callable

from loguru import logger


class InMemorySessionStore:
    def __init__(self, ttl_minutes: int = 30, on_expire: Optional[Callable] = None):
        self._data: Dict[str, Dict[str, Any]] = {}
        self._last_access: Dict[str, float] = {}
        self._ttl_seconds = ttl_minutes * 60
        self._on_expire = on_expire  # callback(session_id, session_data)

    def get(self, session_id: str, default: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        self._last_access[session_id] = time.time()
        if session_id in self._data:
            return self._data[session_id]
        if default is not None:
            return default
        # 不在 _data 且無 default 時，建立預設 session
        default_session_state = {
            "cart": [],
            "pending_frames": [],
            "last_user_text": None,
            "state": "idle",
        }
        self._data[session_id] = default_session_state
        return default_session_state

    def set(self, session_id: str, state: Dict[str, Any]) -> None:
        self._data[session_id] = state
        self._last_access[session_id] = time.time()

    def clear(self, session_id: str) -> None:
        self._data.pop(session_id, None)
        self._last_access.pop(session_id, None)

    def cleanup(self) -> int:
        """清除過期 session，回傳清除數量"""
        now = time.time()
        expired = [
            sid for sid, ts in self._last_access.items()
            if now - ts > self._ttl_seconds
        ]
        for sid in expired:
            if self._on_expire and sid in self._data:
                try:
                    self._on_expire(sid, self._data[sid])
                except Exception as e:
                    logger.error("Session 過期回調失敗 ({}): {}", sid, e)
            self._data.pop(sid, None)
            self._last_access.pop(sid, None)
        if expired:
            logger.info("清除 {} 個過期 session", len(expired))
        return len(expired)

    @property
    def active_count(self) -> int:
        return len(self._data)
