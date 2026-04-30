"""LLM 集成測試"""

import pytest
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

        # 飲料杯型（clarify_policy 統一用 "中冰還是中溫？" 問 size/temp）
        msg = dm.get_clarify_message("drink", ["size"])
        assert "中冰" in msg or "中溫" in msg

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
        assert "明白" in result or "說一次" in result or "想點哪一類" in result


class TestSessionContextIntegration:
    """會話上下文集成測試"""

    def test_session_context_from_session(self, store):
        """測試從會話提取上下文"""
        from src.dm.session_context import SessionContext

        session = {
            "cart": [{"itemtype": "drink", "drink": "豆漿"}],
            "pending_frames": [{"itemtype": "riceball", "missing_slots": ["flavor"]}],
            "status": "OPEN",
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

        session = {"cart": [], "pending_frames": [], "status": "OPEN"}

        context = SessionContext.from_session(session)
        assert context.cart_count == 0
        assert context.pending_count == 0
        assert context.has_main_item is False
        assert context.has_drink is False
        assert context.last_failed_attempt is None

    def test_session_context_carries_last_failed_attempt(self, store):
        """multi-turn 接續：上輪 add 失敗的 provided/missing 要進 SessionContext"""
        from src.dm.session_context import SessionContext

        session = {
            "cart": [],
            "pending_frames": [],
            "status": "OPEN",
            "last_failed_attempt": {
                "item_name": "套餐B",
                "missing": ["flavor"],
                "provided": {"temp": "冰"},
            },
        }

        context = SessionContext.from_session(session)
        assert context.last_failed_attempt is not None
        assert context.last_failed_attempt["item_name"] == "套餐B"
        assert context.last_failed_attempt["missing"] == ["flavor"]
        assert context.last_failed_attempt["provided"] == {"temp": "冰"}


class TestSystemPromptContextRendering:
    """system_prompts._format_session_context 注入待補品項區塊"""

    def test_format_includes_last_failed_attempt(self):
        from src.dm.session_context import SessionContext
        from src.dm.system_prompts import SystemPromptBuilder

        ctx = SessionContext(
            cart_count=0,
            cart_items=[],
            has_main_item=False,
            has_drink=False,
            pending_count=0,
            pending_items=[],
            current_status="OPEN",
            last_failed_attempt={
                "item_name": "套餐B",
                "missing": ["flavor"],
                "provided": {"temp": "冰"},
            },
        )
        text = SystemPromptBuilder()._format_session_context(ctx)
        assert "套餐B" in text
        assert "temp=冰" in text
        assert "缺：flavor" in text

    def test_format_omits_block_when_no_failed_attempt(self):
        from src.dm.session_context import SessionContext
        from src.dm.system_prompts import SystemPromptBuilder

        ctx = SessionContext(
            cart_count=0,
            cart_items=[],
            has_main_item=False,
            has_drink=False,
            pending_count=0,
            pending_items=[],
            current_status="OPEN",
        )
        text = SystemPromptBuilder()._format_session_context(ctx)
        assert "待補品項" not in text


class TestAddComboMissingFields:
    """add_combo 缺必填欄位時回 structured missing list"""

    def test_add_combo_missing_temp_returns_structured(self):
        from src.dm.tool_registry import ToolRegistry
        from src.dm.dialogue_manager import DialogueManager
        from src.dm.session_store import InMemorySessionStore

        store = InMemorySessionStore()
        dm = DialogueManager(store=store)
        registry = ToolRegistry(dm, store)
        registry.set_session_id("t1")

        result = registry.add_combo(combo_name="套餐B", flavor="花生")
        assert result["ok"] is False
        assert "temp" in result.get("missing", [])

    def test_add_combo_missing_flavor_for_combo_b(self):
        from src.dm.tool_registry import ToolRegistry
        from src.dm.dialogue_manager import DialogueManager
        from src.dm.session_store import InMemorySessionStore

        store = InMemorySessionStore()
        dm = DialogueManager(store=store)
        registry = ToolRegistry(dm, store)
        registry.set_session_id("t2")

        result = registry.add_combo(combo_name="套餐B", temp="冰")
        assert result["ok"] is False
        assert "flavor" in result.get("missing", [])


class TestMantouFlavorRouting:
    """饅頭 flavor 欄位路由 — [ADD:饅頭夾蛋|flavor=黑糖] 重建為「黑糖饅頭」"""

    def test_mantou_with_flavor_routes_to_specific_item(self):
        from src.dm.tool_registry import ToolRegistry
        from src.dm.dialogue_manager import DialogueManager
        from src.dm.session_store import InMemorySessionStore

        store = InMemorySessionStore()
        dm = DialogueManager(store=store)
        registry = ToolRegistry(dm, store)
        registry.set_session_id("mt1")

        result = registry.add_item(name="饅頭夾蛋", flavor="黑糖")
        assert result["ok"] is True
        session = store.get("mt1")
        assert session["cart"]
        item = session["cart"][-1]
        assert "黑糖" in item.get("menu_name", "") or "黑糖" in item.get("flavor", "")


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
