# -*- coding: utf-8 -*-
"""b9 批次 A 族修復 regression

- b9-10 果醬吐司變體錯配：裸「果醬吐司」fuzzy 解到草莓/薄片，regex 覆蓋 LLM 明給的 flavor/size
- b9-05 糖度矛盾：[ADD:有糖豆漿|customization=無糖] 品項與客製矛盾 → 翻轉品項
- b9-07 總匯俗稱：「總匯」→ 醬燒肉片總匯吐司
"""

import pytest

from src.dm.dialogue_manager import DialogueManager
from src.dm.session_store import InMemorySessionStore
from src.dm.tool_registry import ToolRegistry


@pytest.fixture
def registry():
    store = InMemorySessionStore()
    dm = DialogueManager(store=store)
    tr = ToolRegistry(dm, store)
    tr.set_session_id("b9-batch-a-test")
    return tr


class TestJamToastParamsWin:
    """b9-10：LLM 明給的 flavor/size 參數優先於 resolved_name regex 抽取"""

    def test_bare_name_with_params(self, registry):
        # [ADD:果醬吐司|flavor=花生|size=厚片] — 裸名 fuzzy 解到草莓/薄片不可覆蓋參數
        r = registry.add_item(name="果醬吐司", flavor="花生", size="厚片")
        assert r["ok"]
        item = registry.get_current_session()["cart"][0]
        assert item["jam_toast"] == "果醬吐司(花生/厚片)"

    def test_bare_name_flavor_only_defaults_thin(self, registry):
        r = registry.add_item(name="果醬吐司", flavor="巧克力")
        assert r["ok"]
        item = registry.get_current_session()["cart"][0]
        assert item["jam_toast"] == "果醬吐司(巧克力/薄片)"

    def test_alias_name_without_params(self, registry):
        # 俗稱路徑不受影響：「花生厚片」→ 果醬吐司(花生/厚片)
        r = registry.add_item(name="花生厚片")
        assert r["ok"]
        item = registry.get_current_session()["cart"][0]
        assert item["jam_toast"] == "果醬吐司(花生/厚片)"

    def test_bare_name_no_flavor_asks(self, registry):
        r = registry.add_item(name="果醬吐司")
        assert not r["ok"]
        assert "flavor" in r.get("missing", [])


class TestSugarVariantFlip:
    """b9-05：糖度客製與品項矛盾時翻轉品項"""

    def test_sugared_plus_sugarfree_custom_flips(self, registry):
        r = registry.add_item(name="有糖豆漿", size="中杯", temp="溫", customization="無糖")
        assert r["ok"]
        item = registry.get_current_session()["cart"][0]
        assert item["drink"] == "無糖豆漿"
        assert not item.get("customization")

    def test_sugarfree_plus_sugared_custom_flips(self, registry):
        r = registry.add_item(name="無糖豆漿", size="大杯", temp="冰", customization="有糖")
        assert r["ok"]
        item = registry.get_current_session()["cart"][0]
        assert item["drink"] == "有糖豆漿"

    def test_flip_keeps_other_customizations(self, registry):
        r = registry.add_item(name="有糖豆漿", size="中杯", temp="冰", customization="無糖,去冰")
        assert r["ok"]
        item = registry.get_current_session()["cart"][0]
        assert item["drink"] == "無糖豆漿"
        assert item.get("customization") == "去冰"

    def test_no_variant_keeps_customization(self, registry):
        # 紅茶沒有無糖變體 → 不翻轉，客製保留給廚房
        r = registry.add_item(name="精選紅茶", size="中杯", temp="冰", customization="無糖")
        assert r["ok"]
        item = registry.get_current_session()["cart"][0]
        assert item["drink"] == "精選紅茶"
        assert item.get("customization") == "無糖"


class TestClubSandwichAlias:
    """b9-07：「總匯」俗稱解析"""

    def test_zonghui(self, registry):
        info = registry._resolve_item_name("總匯")
        assert info is not None
        assert info["resolved_name"] == "醬燒肉片總匯吐司"

    def test_zonghui_toast(self, registry):
        info = registry._resolve_item_name("總匯吐司")
        assert info is not None
        assert info["resolved_name"] == "醬燒肉片總匯吐司"

    def test_zonghui_sandwich(self, registry):
        info = registry._resolve_item_name("總匯三明治")
        assert info is not None
        assert info["resolved_name"] == "醬燒肉片總匯吐司"


class TestTotalQueryShortcircuit:
    """b9-06/b9-08：總價查詢 pre-LLM 兜底（LLM 會幻覺空車/載體謊言）"""

    @staticmethod
    def _run(text, cart):
        """驅動 process_input_stream；LLM mock 一被呼叫就 raise →
        觸發降級 fallback 事件，以此區分「規則層攔截」vs「進了 LLM 路徑」。
        """
        import asyncio
        from unittest.mock import MagicMock, patch
        from src.api.voice_router import StreamingDMAdapter

        store = MagicMock()
        session = {"cart": cart, "llm_history": []}
        store.get.return_value = session
        llm = MagicMock()
        llm.run_turn_stream.side_effect = RuntimeError("llm-reached")
        registry = MagicMock()
        # resolver 回 None：詢價規則 5.5 fallthrough，聚焦驗證總價規則行為
        # （5.5 的真 resolver 行為由 test_b15_batch 覆蓋）
        registry._resolve_item_name.return_value = None

        async def _collect():
            with (
                patch("src.services.container.session_store", store),
                patch("src.services.container.llm_caller", llm),
                patch("src.services.container.tool_registry", registry),
            ):
                adapter = StreamingDMAdapter("total-q-test")
                return [e async for e in adapter.process_input_stream(text)]

        events = asyncio.run(_collect())
        reply = "".join(e.get("content", "") for e in events if e.get("type") == "text_delta")
        llm_reached = any(e.get("type") == "fallback" for e in events)
        return reply, llm_reached

    def test_total_query_returns_backend_total(self):
        cart = [{"itemtype": "snack", "snack": "薯餅(1片)", "quantity": 2}]
        reply, llm_reached = self._run("所以現在總共多少錢", cart)
        assert "目前共40元" in reply
        assert not llm_reached

    def test_now_how_much_hits(self):
        cart = [{"itemtype": "snack", "snack": "荷包蛋", "quantity": 1}]
        reply, llm_reached = self._run("現在多少錢", cart)
        assert "目前共15元" in reply
        assert not llm_reached

    def test_item_price_query_not_hijacked(self):
        # 「起司蛋餅多少錢」是單品詢價：不可被總價規則吃掉
        # （resolver mock 回 None 讓 5.5 fallthrough；5.5 真行為見 test_b15_batch）
        cart = [{"itemtype": "snack", "snack": "荷包蛋", "quantity": 1}]
        reply, llm_reached = self._run("起司蛋餅多少錢", cart)
        assert "目前共" not in reply
        assert llm_reached

    def test_checkout_word_not_hijacked(self):
        # 「就這樣 多少錢」帶收單詞 → 交給結帳流程，不攔截
        cart = [{"itemtype": "snack", "snack": "荷包蛋", "quantity": 1}]
        reply, llm_reached = self._run("就這樣 多少錢", cart)
        assert "目前共" not in reply

    def test_empty_cart_not_hijacked(self):
        reply, llm_reached = self._run("多少錢", [])
        assert "目前共" not in reply


class TestIcedRedTeaNormalize:
    """b9-07：「大冰紅」pre-LLM 正規化（LLM 看不懂縮寫會追問溫度後蒸發）"""

    def test_da_bing_hong(self):
        from src.tools.order_router import normalize_text

        assert normalize_text("一杯大冰紅") == "一杯大杯冰紅茶"

    def test_zhong_bing_hong(self):
        from src.tools.order_router import normalize_text

        assert normalize_text("中冰紅謝謝") == "中杯冰紅茶謝謝"


class TestReviewFindings:
    """PR #28 review 發現的修正"""

    def test_flip_before_sold_out_block(self, registry):
        # 有糖豆漿售完但無糖有貨 → [ADD:有糖豆漿|customization=無糖] 翻轉後不該被誤擋
        from unittest.mock import patch

        with patch(
            "src.dm.tool_registry.menu_state_service.get_effective_sold_out",
            return_value={"有糖豆漿(中)", "有糖豆漿(大)", "有糖豆漿"},
        ):
            r = registry.add_item(name="有糖豆漿", size="中杯", temp="溫", customization="無糖")
        assert r["ok"]
        item = registry.get_current_session()["cart"][0]
        assert item["drink"] == "無糖豆漿"

    def test_menu_name_price_query_not_hijacked(self):
        # 「十穀漿多少錢」不在 CONCRETE_ITEM_WORDS，但是菜單品名 → 不可攔截
        cart = [{"itemtype": "snack", "snack": "薯餅(1片)", "quantity": 1}]
        reply, llm_reached = TestTotalQueryShortcircuit._run("十穀漿多少錢", cart)
        assert "目前共" not in reply
        assert llm_reached

    def test_full_drink_name_normalize_no_dup(self):
        # 「大冰紅茶」完整品名不可變成「大杯冰紅茶茶」
        from src.tools.order_router import normalize_text

        assert normalize_text("一杯大冰紅茶謝謝") == "一杯大杯冰紅茶謝謝"
