import json
import time
from typing import Dict, Any, Optional, Callable, Protocol, runtime_checkable

from loguru import logger


@runtime_checkable
class SessionStore(Protocol):
    """Session Store 協定 — InMemory / Redis 共用介面"""

    def get(self, session_id: str, default: Optional[Dict[str, Any]] = None) -> Dict[str, Any]: ...
    def set(self, session_id: str, state: Dict[str, Any]) -> None: ...
    def clear(self, session_id: str) -> None: ...
    def cleanup(self) -> int: ...

    @property
    def active_count(self) -> int: ...


def _default_session_state() -> Dict[str, Any]:
    """建立預設 session 結構"""
    return {
        "cart": [],
        "pending_frames": [],
        "last_user_text": None,
        "state": "idle",
    }


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
        new_session = _default_session_state()
        self._data[session_id] = new_session
        return new_session

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


class RedisSessionStore:
    """Redis-backed Session Store — set() 帶 TTL，get() 刷新 TTL"""

    def __init__(self, redis_url: str, ttl_minutes: int = 30, on_expire: Optional[Callable] = None):
        import redis as redis_lib
        self._redis = redis_lib.from_url(redis_url, decode_responses=True)
        self._url = redis_url
        self._ttl_seconds = ttl_minutes * 60
        self._on_expire = on_expire
        self._prefix = "session:"

    def _key(self, session_id: str) -> str:
        return f"{self._prefix}{session_id}"

    def get(self, session_id: str, default: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        raw = self._redis.get(self._key(session_id))
        if raw is not None:
            # 刷新 TTL
            self._redis.expire(self._key(session_id), self._ttl_seconds)
            return json.loads(raw)
        if default is not None:
            return default
        # 建立預設 session 並存入 Redis
        new_session = _default_session_state()
        self.set(session_id, new_session)
        return new_session

    def set(self, session_id: str, state: Dict[str, Any]) -> None:
        self._redis.setex(
            self._key(session_id),
            self._ttl_seconds,
            json.dumps(state, ensure_ascii=False),
        )

    def clear(self, session_id: str) -> None:
        self._redis.delete(self._key(session_id))

    def cleanup(self) -> int:
        """Redis 自帶 TTL 過期，此方法回傳 0（相容介面）"""
        return 0

    def ping(self) -> bool:
        """健康檢查 — Redis 是否可達"""
        try:
            return self._redis.ping()
        except Exception:
            return False

    @property
    def active_count(self) -> int:
        cursor, count = 0, 0
        while True:
            cursor, keys = self._redis.scan(cursor, match=f"{self._prefix}*", count=100)
            count += len(keys)
            if cursor == 0:
                break
        return count


def create_session_store(
    redis_url: str = "",
    ttl_minutes: int = 30,
    on_expire: Optional[Callable] = None,
) -> SessionStore:
    """工廠函式 — 自動偵測 Redis 可用性，失敗 fallback InMemory"""
    if redis_url:
        try:
            store = RedisSessionStore(redis_url, ttl_minutes, on_expire)
            store._redis.ping()
            logger.info("Session Store: Redis ({})", redis_url)
            return store  # type: ignore[return-value]
        except Exception as e:
            logger.warning("Redis 連線失敗 ({}), fallback InMemory: {}", redis_url, e)
    logger.info("Session Store: InMemory (TTL={}min)", ttl_minutes)
    return InMemorySessionStore(ttl_minutes, on_expire)  # type: ignore[return-value]
