"""LLM 集成測試"""
import pytest
from unittest.mock import Mock
from src.dm.dialogue_manager import DialogueManager
from src.dm.session_store import InMemorySessionStore


@pytest.fixture
def store():
    """創建會話存儲"""
    return InMemorySessionStore()


class TestDialogueManagerBasic:
    """對話管理器基礎測試"""

    def test_dialogue_manager_initialization(self, store):
        """測試對話管理器初始化"""
        dm = DialogueManager(store=store)
        assert dm.store is store

    def test_hardcoded_clarify_message(self, store):
        """測試使用硬編碼澄清問題"""
        dm = DialogueManager(store=store)

        # 飲料溫度
        msg = dm.get_clarify_message("drink", ["temp"])
        assert "冰" in msg or "溫" in msg

        # 飲料杯型
        msg = dm.get_clarify_message("drink", ["size"])
        assert "大杯" in msg or "中杯" in msg

        # 飯糰米種
        msg = dm.get_clarify_message("riceball", ["rice"])
        assert "米" in msg

        # 飯糰口味
        msg = dm.get_clarify_message("riceball", ["flavor"])
        assert "口味" in msg

    def test_unknown_input_returns_clarification(self, store):
        """測試未知輸入返回澄清提示"""
        dm = DialogueManager(store=store)
        session_id = "test_session"
        result = dm.handle(session_id, "xyz 不明白的東西")
        assert "明白" in result or "說一次" in result


class TestSessionContextIntegration:
    """會話上下文集成測試"""

    def test_session_context_from_session(self, store):
        """測試從會話提取上下文"""
        from src.dm.session_context import SessionContext

        session = {
            "cart": [{"itemtype": "drink", "drink": "豆漿"}],
            "pending_frames": [{"itemtype": "riceball", "missing_slots": ["flavor"]}],
            "status": "OPEN"
        }

        context = SessionContext.from_session(session)
        assert context.cart_count == 1
        assert context.has_drink is True
        assert context.pending_count == 1
        assert len(context.cart_items) == 1
        assert len(context.pending_items) == 1

    def test_session_context_empty_session(self, store):
        """測試空會話的上下文"""
        from src.dm.session_context import SessionContext

        session = {
            "cart": [],
            "pending_frames": [],
            "status": "OPEN"
        }

        context = SessionContext.from_session(session)
        assert context.cart_count == 0
        assert context.pending_count == 0
        assert context.has_main_item is False
        assert context.has_drink is False


class TestBackwardCompatibility:
    """向後兼容性測試"""

    def test_old_code_still_works(self, store):
        """測試舊代碼仍然可以工作"""
        dm = DialogueManager(store=store)

        session_id = "test_session"
        result = dm.handle(session_id, "我要飯糰")
        assert isinstance(result, str)

    def test_lm_studio_connection_test_still_passes(self):
        """測試 LM Studio 連線測試仍然通過"""
        import os
        from dotenv import load_dotenv

        load_dotenv()
        lm_studio_url = os.getenv("LM_STUDIO_URL")
        if lm_studio_url:
            assert lm_studio_url.startswith("http")
