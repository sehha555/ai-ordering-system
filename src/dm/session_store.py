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
    def __init__(
        self, ttl_minutes: int = 30, on_expire: Optional[Callable] = None, max_sessions: int = 500
    ):
        self._data: Dict[str, Dict[str, Any]] = {}
        self._last_access: Dict[str, float] = {}
        self._ttl_seconds = ttl_minutes * 60
        self._on_expire = on_expire  # callback(session_id, session_data)
        self._max_sessions = max_sessions

    def get(self, session_id: str, default: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if session_id in self._data:
            self._last_access[session_id] = time.time()
            return self._data[session_id]
        if default is not None:
            return default
        # 容量檢查：達上限時先清過期，仍滿則淘汰最舊
        if len(self._data) >= self._max_sessions:
            self.cleanup()
        if len(self._data) >= self._max_sessions:
            oldest = min(self._last_access, key=self._last_access.get)  # type: ignore[arg-type]
            self._data.pop(oldest, None)
            self._last_access.pop(oldest, None)
            logger.warning(
                "[SessionStore] 達上限 {}，淘汰最舊 session {}", self._max_sessions, oldest[:8]
            )
        # 建立預設 session
        new_session = _default_session_state()
        self._data[session_id] = new_session
        self._last_access[session_id] = time.time()
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
        expired = [sid for sid, ts in self._last_access.items() if now - ts > self._ttl_seconds]
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
    """Redis-backed Session Store — set() 帶 TTL，get() 刷新 TTL

    注意：on_expire callback 透過 Redis keyspace notification 觸發。
    data 參數為空 dict（{}），因 Redis 過期時資料已刪除。
    """

    def __init__(self, redis_url: str, ttl_minutes: int = 30, on_expire: Optional[Callable] = None):
        import redis as redis_lib

        self._redis = redis_lib.from_url(redis_url, decode_responses=True)
        self._url = redis_url
        self._ttl_seconds = ttl_minutes * 60
        self._on_expire = on_expire
        self._prefix = "session:"
        self._listener_thread = None
        if self._on_expire:
            try:
                self._redis.config_set("notify-keyspace-events", "Ex")
            except Exception as e:
                logger.warning("Redis keyspace notification 設定失敗，on_expire 將不觸發: {}", e)
            self._start_keyspace_listener()

    def _start_keyspace_listener(self) -> None:
        """啟動背景 thread，訂閱 Redis keyspace expired 事件"""
        import threading

        def _listen() -> None:
            while True:
                pubsub = self._redis.pubsub()
                try:
                    # 取得 Redis DB index（預設 0）
                    db_index = self._redis.connection_pool.connection_kwargs.get("db", 0)
                    channel = f"__keyevent@{db_index}__:expired"
                    pubsub.subscribe(channel)
                    logger.info("Redis keyspace listener 啟動，訂閱: {}", channel)
                    for message in pubsub.listen():
                        if message["type"] != "message":
                            continue
                        key = message["data"]
                        if not key.startswith(self._prefix):
                            continue
                        session_id = key[len(self._prefix) :]
                        try:
                            # 資料在 Redis 過期時已刪除，callback 收到空 dict
                            self._on_expire(session_id, {})
                        except Exception as e:
                            logger.error("Session 過期回調失敗 ({}): {}", session_id, e)
                except Exception as e:
                    logger.error("Redis keyspace listener 異常，5s 後重連: {}", e)
                finally:
                    try:
                        pubsub.close()
                    except Exception:
                        pass
                time.sleep(5)

        t = threading.Thread(
            target=_listen,
            daemon=True,
            name="redis-session-expire-listener",
        )
        t.start()
        self._listener_thread = t

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
