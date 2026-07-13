# -*- coding: utf-8 -*-
"""b10 批次修復 regression

- b10-06 果醬吐司口味複製：「再一份花生薄片」LLM 複製 cart 前品項發 flavor=巧克力，
  slot-strip 的 context 輪豁免放行 → 封閉值域 text 佐證修正
- b10-06 輔助：薄片俗稱系列（花生薄片 → 果醬吐司(花生/薄片)）
- b10-02 存在性查詢謊報：「有賣咖啡嗎」→「沒有賣咖啡」（菜單有純鮮奶咖啡）
  → pre-LLM resolver 驗證直答 + pending_offer 指代橋接（「來一份」）
"""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from src.api.text_tag_executor import execute_tags
from src.dm.dialogue_manager import DialogueManager
from src.dm.session_store import InMemorySessionStore
from src.dm.tool_registry import ToolRegistry


def _make_session(cart=None):
    return {
        "cart": cart if cart is not None else [],
        "llm_history": [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "raw"},
        ],
    }


@pytest.fixture
def mock_registry():
    reg = MagicMock()
    reg.add_item.return_value = {"ok": True, "item_id": "i1", "message": "已加入"}
    with patch("src.services.container.tool_registry", reg):
        yield reg


@pytest.fixture
def real_registry():
    store = InMemorySessionStore()
    dm = DialogueManager(store=store)
    tr = ToolRegistry(dm, store)
    tr.set_session_id("b10-test")
    return tr


class TestJamTextEvidenceFix:
    """b10-06：果醬吐司封閉值域 text 佐證修正"""

    @pytest.mark.asyncio
    async def test_copied_flavor_corrected_by_text(self, mock_registry):
        # LLM 複製 cart 前品項發 巧克力/厚片，text 說花生薄片 → 以 text 為準
        session = _make_session()
        await execute_tags(
            "[ADD:果醬吐司|flavor=巧克力|size=厚片]好～", "再一份花生薄片", session, "s1"
        )
        kwargs = mock_registry.add_item.call_args.kwargs
        assert kwargs["flavor"] == "花生"
        assert kwargs["size"] == "薄片"

    @pytest.mark.asyncio
    async def test_matching_tag_unchanged(self, mock_registry):
        session = _make_session()
        await execute_tags(
            "[ADD:果醬吐司|flavor=花生|size=薄片]好～", "一份花生薄片", session, "s1"
        )
        kwargs = mock_registry.add_item.call_args.kwargs
        assert kwargs["flavor"] == "花生"
        assert kwargs["size"] == "薄片"

    @pytest.mark.asyncio
    async def test_multi_flavor_text_ambiguous_no_change(self, mock_registry):
        # text 含兩種口味（多品項句）→ 語意模糊不修正
        session = _make_session()
        await execute_tags(
            "[ADD:果醬吐司|flavor=花生|size=厚片]好～",
            "一份花生厚片和一份巧克力薄片",
            session,
            "s1",
        )
        kwargs = mock_registry.add_item.call_args_list[0].kwargs
        assert kwargs["flavor"] == "花生"

    @pytest.mark.asyncio
    async def test_non_jam_item_untouched(self, mock_registry):
        # 非果醬吐司品項不受此修正影響
        session = _make_session()
        await execute_tags("[ADD:鮪魚飯糰|rice=紫米]好～", "鮪魚飯糰紫米", session, "s1")
        kwargs = mock_registry.add_item.call_args.kwargs
        assert kwargs["name"] == "鮪魚飯糰"
        assert "flavor" not in kwargs or kwargs.get("flavor") != "花生"


class TestThinToastAliases:
    """b10-06 輔助：薄片俗稱"""

    def test_thin_aliases_resolve(self, real_registry):
        for alias, expected in [
            ("花生薄片", "果醬吐司(花生/薄片)"),
            ("巧克力薄片", "果醬吐司(巧克力/薄片)"),
        ]:
            info = real_registry._resolve_item_name(alias)
            assert info is not None, alias
            assert info["resolved_name"] == expected


class TestExistenceQuery:
    """b10-02：存在性查詢 pre-LLM 攔截"""

    @staticmethod
    def _run(text, session_extra=None):
        from src.api.voice_router import StreamingDMAdapter

        store = MagicMock()
        session = {"cart": [], "llm_history": []}
        if session_extra:
            session.update(session_extra)
        store.get.return_value = session

        llm = MagicMock()
        llm.run_turn_stream.side_effect = RuntimeError("llm-reached")

        # 存在性查詢需要真 resolver
        real_store = InMemorySessionStore()
        dm = DialogueManager(store=real_store)
        reg = ToolRegistry(dm, real_store)

        async def _collect():
            with (
                patch("src.services.container.session_store", store),
                patch("src.services.container.llm_caller", llm),
                patch("src.services.container.tool_registry", reg),
            ):
                adapter = StreamingDMAdapter("exist-q-test")
                return [e async for e in adapter.process_input_stream(text)]

        events = asyncio.run(_collect())
        reply = "".join(e.get("content", "") for e in events if e.get("type") == "text_delta")
        llm_reached = any(e.get("type") == "fallback" for e in events)
        return reply, llm_reached, session, llm

    def test_coffee_exists(self):
        reply, llm_reached, session, _ = self._run("你們有賣咖啡嗎")
        assert "有喔" in reply
        assert "純鮮奶咖啡" in reply
        assert not llm_reached
        assert session["pending_offer"] == "純鮮奶咖啡"

    def test_radish_cake_exists_with_price(self):
        reply, llm_reached, session, _ = self._run("有沒有蘿蔔糕")
        assert "有喔" in reply
        assert "蘿蔔糕" in reply
        assert not llm_reached

    def test_unknown_item_falls_through(self):
        reply, llm_reached, _, _ = self._run("有沒有牛肉麵")
        assert "有喔" not in reply
        assert llm_reached

    def test_order_sentence_not_intercepted(self):
        # 「我要一個蛋餅」非存在性問句 → 走 LLM
        reply, llm_reached, _, _ = self._run("我要一個原味蛋餅")
        assert llm_reached


class TestOfferBridge:
    """b10-02：pending_offer 肯定句改寫"""

    def test_affirm_rewritten_to_order(self):
        _, _, session, llm = TestExistenceQuery._run(
            "來一份", session_extra={"pending_offer": "港式蘿蔔糕"}
        )
        assert llm.run_turn_stream.call_args.kwargs["user_text"] == "我要一份港式蘿蔔糕"
        assert "pending_offer" not in session  # 單輪有效，用過即棄

    def test_affirm_with_quantity(self):
        _, _, _, llm = TestExistenceQuery._run(
            "來兩份", session_extra={"pending_offer": "港式蘿蔔糕"}
        )
        assert llm.run_turn_stream.call_args.kwargs["user_text"] == "我要兩份港式蘿蔔糕"

    def test_non_affirm_not_rewritten(self):
        _, _, session, llm = TestExistenceQuery._run(
            "我要一個原味蛋餅", session_extra={"pending_offer": "港式蘿蔔糕"}
        )
        assert llm.run_turn_stream.call_args.kwargs["user_text"] == "我要一個原味蛋餅"
        assert "pending_offer" not in session  # 沒接單也棄掉，不跨輪殘留

    def test_negative_not_rewritten(self):
        _, _, _, llm = TestExistenceQuery._run(
            "不用了", session_extra={"pending_offer": "港式蘿蔔糕"}
        )
        assert llm.run_turn_stream.call_args.kwargs["user_text"] == "不用了"


class TestJamTagNameVariants:
    """b10-06 第三種 tag 變體：[ADD:花生吐司]（LLM 三種發法全覆蓋）"""

    def test_flavor_toast_alias_resolves(self, real_registry):
        info = real_registry._resolve_item_name("花生吐司")
        assert info is not None
        assert info["resolved_name"] == "果醬吐司(花生/薄片)"

    @pytest.mark.asyncio
    async def test_flavor_toast_tag_thickness_from_text(self, mock_registry):
        # tag [ADD:花生吐司]、text 說厚片 → size 以 text 為準
        session = _make_session()
        await execute_tags("[ADD:花生吐司]好～", "一份花生厚片", session, "s1")
        kwargs = mock_registry.add_item.call_args.kwargs
        assert kwargs["flavor"] == "花生"
        assert kwargs["size"] == "厚片"

    @pytest.mark.asyncio
    async def test_peanut_drink_not_misfired(self, mock_registry):
        # 花生糙米漿含口味詞但無吐司/厚薄詞 → 不觸發 jam 修正
        session = _make_session()
        await execute_tags(
            "[ADD:花生糙米漿|size=中|temp=冰]好～", "一杯中杯冰花生糙米漿", session, "s1"
        )
        kwargs = mock_registry.add_item.call_args.kwargs
        assert "flavor" not in kwargs

    def test_flavor_prefixed_full_name_resolves(self, real_registry):
        # 第四種變體：[ADD:巧克力果醬吐司]（口味前綴全名）
        info = real_registry._resolve_item_name("巧克力果醬吐司")
        assert info is not None
        assert info["resolved_name"] == "果醬吐司(巧克力/薄片)"

    @pytest.mark.asyncio
    async def test_prefixed_name_thickness_from_text(self, mock_registry):
        # tag 巧克力果醬吐司、text 說厚片 → size 以 text 為準
        session = _make_session()
        await execute_tags(
            "[ADD:巧克力果醬吐司]好～", "一份巧克力厚片 一杯豆漿", session, "s1"
        )
        kwargs = mock_registry.add_item.call_args_list[0].kwargs
        assert kwargs["flavor"] == "巧克力"
        assert kwargs["size"] == "厚片"
