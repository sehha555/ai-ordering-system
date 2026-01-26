"""LLM 集成與備選行為測試"""
import pytest
from unittest.mock import Mock, patch
from src.dm.dialogue_manager import DialogueManager
from src.dm.llm_router import LLMRouter
from src.dm.llm_clarifier import LLMClarifier
from src.dm.session_store import InMemorySessionStore


@pytest.fixture
def mock_llm():
    """創建 Mock LLM"""
    mock = Mock()
    return mock


@pytest.fixture
def store():
    """創建會話存儲"""
    return InMemorySessionStore()


class TestDialogueManagerWithoutLLM:
    """不使用 LLM 的對話管理器測試（向後兼容性）"""

    def test_dialogue_manager_without_llm_components(self, store):
        """測試不使用 LLM 元件時的行為"""
        dm = DialogueManager(store=store, llm_enabled=False)
        assert dm.llm_router is None
        assert dm.llm_clarifier is None

    def test_hardcoded_clarify_message(self, store):
        """測試使用硬編碼澄清問題"""
        dm = DialogueManager(store=store, llm_enabled=False)

        # 應該使用硬編碼問題
        msg = dm.get_clarify_message("drink", ["temp"])
        assert "冰" in msg or "溫" in msg


class TestDialogueManagerWithLLM:
    """使用 LLM 的對話管理器測試"""

    def test_dialogue_manager_with_llm_components(self, store, mock_llm):
        """測試啟用 LLM 元件"""
        router = LLMRouter(mock_llm)
        clarifier = LLMClarifier(mock_llm)

        dm = DialogueManager(
            store=store,
            llm_router=router,
            llm_clarifier=clarifier,
            llm_enabled=True
        )

        assert dm.llm_router is router
        assert dm.llm_clarifier is clarifier

    def test_dialogue_manager_llm_disabled_ignores_components(self, store, mock_llm):
        """測試禁用時忽略 LLM 元件"""
        router = LLMRouter(mock_llm)
        clarifier = LLMClarifier(mock_llm)

        dm = DialogueManager(
            store=store,
            llm_router=router,
            llm_clarifier=clarifier,
            llm_enabled=False
        )

        # llm_enabled=False 應該忽略傳入的元件
        assert dm.llm_router is None
        assert dm.llm_clarifier is None


class TestLLMRouterFallback:
    """LLM 路由器備選行為測試"""

    def test_unknown_route_with_llm_high_confidence(self, store, mock_llm):
        """測試 LLM 提供高信心度分類"""
        router = LLMRouter(mock_llm)
        dm = DialogueManager(
            store=store,
            llm_router=router,
            llm_enabled=True
        )

        # 模擬 LLM 響應：高信心度
        mock_llm.call_llm.return_value = {
            "choices": [{
                "message": {
                    "content": '{"route_type": "riceball", "confidence": 0.85, "reasoning": "客人說飯糰", "alternatives": []}'
                }
            }]
        }

        session_id = "test_session"
        result = dm.handle(session_id, "我想吃飯糰")

        # 應該被路由到飯糰，而不是返回「不明白」
        assert "飯糰" in result or "還需要什麼" in result

    def test_unknown_route_with_llm_low_confidence(self, store, mock_llm):
        """測試 LLM 提供低信心度分類"""
        router = LLMRouter(mock_llm)
        dm = DialogueManager(
            store=store,
            llm_router=router,
            llm_enabled=True
        )

        # 模擬 LLM 響應：低信心度
        mock_llm.call_llm.return_value = {
            "choices": [{
                "message": {
                    "content": '{"route_type": "drink", "confidence": 0.5, "reasoning": "不確定", "alternatives": ["riceball"]}'
                }
            }]
        }

        session_id = "test_session"
        result = dm.handle(session_id, "xyz 不明白")

        # 低信心度時應該返回「不明白」
        assert "明白" in result or "說一次" in result

    def test_unknown_route_llm_exception_fallback(self, store, mock_llm):
        """測試 LLM 失敗時備選至硬編碼"""
        router = LLMRouter(mock_llm)
        dm = DialogueManager(
            store=store,
            llm_router=router,
            llm_enabled=True
        )

        # 模擬 LLM 異常
        mock_llm.call_llm.side_effect = Exception("LLM 連線失敗")

        session_id = "test_session"
        result = dm.handle(session_id, "xyz 異常測試")

        # 應該優雅地備選至硬編碼回應
        assert "明白" in result or "說一次" in result


class TestLLMClarifierFallback:
    """LLM 澄清器備選行為測試"""

    def test_clarify_with_llm(self, store, mock_llm):
        """測試使用 LLM 生成澄清問題"""
        clarifier = LLMClarifier(mock_llm)
        dm = DialogueManager(
            store=store,
            llm_clarifier=clarifier,
            llm_enabled=True
        )

        # 模擬 LLM 響應
        mock_llm.call_llm.return_value = {
            "choices": [{
                "message": {
                    "content": "你想要什麼口味的飯糰呢？"
                }
            }]
        }

        msg = dm.get_clarify_message("riceball", ["flavor"])
        assert "口味" in msg

    def test_clarify_llm_exception_fallback(self, store, mock_llm):
        """測試 LLM 澄清失敗時備選至硬編碼"""
        clarifier = LLMClarifier(mock_llm)
        dm = DialogueManager(
            store=store,
            llm_clarifier=clarifier,
            llm_enabled=True
        )

        # 模擬 LLM 異常
        mock_llm.call_llm.side_effect = Exception("LLM 失敗")

        msg = dm.get_clarify_message("drink", ["temp"])

        # 應該備選至硬編碼問題
        assert "冰" in msg or "溫" in msg


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
        """測試舊代碼（不使用 LLM）仍然可以工作"""
        # 這是原始的初始化方式
        dm = DialogueManager(store=store)

        session_id = "test_session"
        # 應該能夠正常處理
        result = dm.handle(session_id, "我要飯糰")
        assert isinstance(result, str)

    def test_lm_studio_connection_test_still_passes(self):
        """測試 LM Studio 連線測試仍然通過"""
        # 這是一個簡單的測試確保環境設置正確
        import os
        from dotenv import load_dotenv

        load_dotenv()
        lm_studio_url = os.getenv("LM_STUDIO_URL")
        # 如果配置了 LM Studio，應該能夠訪問
        if lm_studio_url:
            assert lm_studio_url.startswith("http")
