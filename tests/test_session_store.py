"""Session Store 單元測試 — InMemory + Redis（mock）"""
import json
import time
from unittest.mock import MagicMock, patch

import pytest

from src.dm.session_store import (
    InMemorySessionStore,
    RedisSessionStore,
    SessionStore,
    create_session_store,
    _default_session_state,
)


# ============================================================
# InMemorySessionStore
# ============================================================


class TestInMemorySessionStore:
    def test_get_creates_default_session(self):
        store = InMemorySessionStore()
        session = store.get("s1")
        assert session["cart"] == []
        assert session["state"] == "idle"

    def test_get_returns_same_reference(self):
        store = InMemorySessionStore()
        s1 = store.get("s1")
        s1["cart"].append({"item": "test"})
        s2 = store.get("s1")
        assert len(s2["cart"]) == 1

    def test_get_with_default(self):
        store = InMemorySessionStore()
        default = {"custom": True}
        result = store.get("missing", default=default)
        assert result == {"custom": True}

    def test_set_and_get(self):
        store = InMemorySessionStore()
        store.set("s1", {"cart": [{"item": "飯糰"}]})
        session = store.get("s1")
        assert session["cart"][0]["item"] == "飯糰"

    def test_clear(self):
        store = InMemorySessionStore()
        store.get("s1")
        assert store.active_count == 1
        store.clear("s1")
        assert store.active_count == 0

    def test_cleanup_removes_expired(self):
        store = InMemorySessionStore(ttl_minutes=0)  # 0 分鐘 = 立即過期
        store.get("s1")
        store.get("s2")
        time.sleep(0.01)
        cleaned = store.cleanup()
        assert cleaned == 2
        assert store.active_count == 0

    def test_cleanup_keeps_active(self):
        store = InMemorySessionStore(ttl_minutes=60)
        store.get("s1")
        cleaned = store.cleanup()
        assert cleaned == 0
        assert store.active_count == 1

    def test_on_expire_callback(self):
        expired_sessions = []
        store = InMemorySessionStore(
            ttl_minutes=0,
            on_expire=lambda sid, data: expired_sessions.append(sid),
        )
        store.get("s1")
        time.sleep(0.01)
        store.cleanup()
        assert "s1" in expired_sessions

    def test_active_count(self):
        store = InMemorySessionStore()
        assert store.active_count == 0
        store.get("s1")
        store.get("s2")
        assert store.active_count == 2

    def test_implements_protocol(self):
        store = InMemorySessionStore()
        assert isinstance(store, SessionStore)


# ============================================================
# RedisSessionStore（使用 mock Redis）
# ============================================================


class TestRedisSessionStore:
    @pytest.fixture
    def mock_redis(self):
        with patch("redis.from_url") as mock_from_url:
            mock_client = MagicMock()
            mock_from_url.return_value = mock_client
            yield mock_client

    def test_get_creates_default_when_missing(self, mock_redis):
        mock_redis.get.return_value = None
        store = RedisSessionStore("redis://localhost:6379", ttl_minutes=30)

        session = store.get("s1")

        assert session == _default_session_state()
        # 確認有寫回 Redis
        mock_redis.setex.assert_called_once()

    def test_get_returns_existing_session(self, mock_redis):
        existing = {"cart": [{"item": "飯糰"}], "state": "idle"}
        mock_redis.get.return_value = json.dumps(existing)
        store = RedisSessionStore("redis://localhost:6379", ttl_minutes=30)

        session = store.get("s1")

        assert session["cart"][0]["item"] == "飯糰"
        # 確認有刷新 TTL
        mock_redis.expire.assert_called_once_with("session:s1", 1800)

    def test_get_with_default(self, mock_redis):
        mock_redis.get.return_value = None
        store = RedisSessionStore("redis://localhost:6379")

        result = store.get("missing", default={"custom": True})

        assert result == {"custom": True}
        mock_redis.setex.assert_not_called()

    def test_set_serializes_to_redis(self, mock_redis):
        store = RedisSessionStore("redis://localhost:6379", ttl_minutes=15)
        state = {"cart": [{"item": "豆漿"}]}

        store.set("s1", state)

        mock_redis.setex.assert_called_once_with(
            "session:s1",
            900,
            json.dumps(state, ensure_ascii=False),
        )

    def test_clear_deletes_key(self, mock_redis):
        store = RedisSessionStore("redis://localhost:6379")
        store.clear("s1")
        mock_redis.delete.assert_called_once_with("session:s1")

    def test_cleanup_returns_zero(self, mock_redis):
        store = RedisSessionStore("redis://localhost:6379")
        assert store.cleanup() == 0

    def test_active_count_scans_keys(self, mock_redis):
        # 模擬 scan 回傳
        mock_redis.scan.side_effect = [
            (5, ["session:s1", "session:s2"]),
            (0, ["session:s3"]),
        ]
        store = RedisSessionStore("redis://localhost:6379")
        assert store.active_count == 3


# ============================================================
# create_session_store 工廠函式
# ============================================================


class TestCreateSessionStore:
    def test_empty_url_returns_inmemory(self):
        store = create_session_store(redis_url="", ttl_minutes=10)
        assert isinstance(store, InMemorySessionStore)

    def test_redis_url_with_connection_failure_fallback(self):
        with patch("redis.from_url") as mock_from_url:
            mock_client = MagicMock()
            mock_client.ping.side_effect = ConnectionError("refused")
            mock_from_url.return_value = mock_client

            store = create_session_store(redis_url="redis://bad:6379")
            assert isinstance(store, InMemorySessionStore)

    def test_redis_url_with_successful_connection(self):
        with patch("redis.from_url") as mock_from_url:
            mock_client = MagicMock()
            mock_client.ping.return_value = True
            mock_from_url.return_value = mock_client

            store = create_session_store(redis_url="redis://good:6379")
            assert isinstance(store, RedisSessionStore)
