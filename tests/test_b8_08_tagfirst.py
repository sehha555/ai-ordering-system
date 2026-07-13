# -*- coding: utf-8 -*-
"""b8-08 tag-first 補槽鏈 regression

多槽套餐佔位 tag 進後端後的補槽三防護：
- retry-fix：LLM 發錯值（text 有正確值）→ 修正而非 strip（strip 會讓資訊蒸發）
- provided merge：前幾輪已提供的槽補回 kwargs（attempt 覆寫不再遺失累積）
- attempt text 直補：LLM 純 prose 不發 tag 的補槽輪，槽值直接從 text 撿
"""

import pytest
from unittest.mock import MagicMock, patch

from src.api.text_tag_executor import _slot_value_from_text, execute_tags


def _session_with_attempt(item_name, missing, provided=None):
    return {
        "cart": [],
        "llm_history": [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "raw"},
        ],
        "last_failed_attempt": {
            "item_name": item_name,
            "missing": list(missing),
            "provided": dict(provided or {}),
            "message": "追問",
        },
    }


class TestSlotValueFromText:
    def test_noodle_from_text(self):
        assert _slot_value_from_text("noodle", "黑椒 油麵") == "油麵"

    def test_negated_value_skipped(self):
        assert _slot_value_from_text("noodle", "不要油麵 烏龍好了") == "烏龍麵"

    def test_no_value_returns_none(self):
        assert _slot_value_from_text("noodle", "紅茶去冰") is None

    def test_ambiguous_two_values_none(self):
        assert _slot_value_from_text("rice", "紫米還是白米都可以") is None

    def test_flavor_iron_noodle_alias(self):
        assert _slot_value_from_text("flavor", "黑胡椒的") == "黑椒"


class TestProvidedMerge:
    """b12-08 套餐五：「溫的」→「起司的」每輪只留當輪槽 → 永動輪"""

    @pytest.mark.asyncio
    async def test_prev_provided_merged_into_retry(self):
        # attempt 已有 temp=溫，本輪 LLM 只發 flavor（temp 被 strip 也無妨）
        reg = MagicMock()
        reg.add_item.return_value = {"ok": True, "item_id": "combo_1", "message": "已加入"}
        session = _session_with_attempt("套餐五", ["flavor"], {"temp": "溫"})
        with patch("src.services.container.tool_registry", reg):
            await execute_tags("[ADD:套餐五|flavor=起司]好～", "起司的", session, "s1")
        kwargs = reg.add_item.call_args.kwargs
        assert kwargs["temp"] == "溫"  # 跨輪記憶 merge 回來
        assert kwargs["flavor"] == "起司"

    @pytest.mark.asyncio
    async def test_llm_restated_stale_slot_not_stripped_away(self):
        # LLM 重發全參數（temp=溫 本輪 text 無佐證）→ provided 豁免 + merge 保住
        reg = MagicMock()
        reg.add_item.return_value = {"ok": True, "item_id": "combo_1", "message": "已加入"}
        session = _session_with_attempt("套餐五", ["flavor"], {"temp": "溫"})
        with patch("src.services.container.tool_registry", reg):
            await execute_tags("[ADD:套餐五|temp=溫|flavor=起司]好～", "起司的", session, "s1")
        kwargs = reg.add_item.call_args.kwargs
        assert kwargs["temp"] == "溫"
        assert kwargs["flavor"] == "起司"


class TestNoTagSlotFill:
    """補槽輪 LLM 純 prose 不發 tag → attempt 缺槽 text 直補"""

    @pytest.mark.asyncio
    async def test_partial_fill_accumulates(self):
        reg = MagicMock()
        session = _session_with_attempt("套餐六", ["temp", "noodle"], {"flavor": "黑椒"})
        with patch("src.services.container.tool_registry", reg):
            await execute_tags("好的～", "油麵", session, "s1")
        att = session["last_failed_attempt"]
        assert att["provided"]["noodle"] == "油麵"
        assert att["missing"] == ["temp"]
        reg.add_item.assert_not_called()  # 未齊不 retry

    @pytest.mark.asyncio
    async def test_full_fill_retries_and_clears(self):
        reg = MagicMock()
        reg.add_item.return_value = {"ok": True, "item_id": "combo_1", "message": "已加入"}
        session = _session_with_attempt("套餐五", ["temp"], {"flavor": "起司"})
        with patch("src.services.container.tool_registry", reg):
            await execute_tags("好的～", "溫的", session, "s1")
        reg.add_item.assert_called_once_with(name="套餐五", flavor="起司", temp="溫")
        assert session["last_failed_attempt"] is None

    @pytest.mark.asyncio
    async def test_unrelated_prose_untouched(self):
        # 閒聊/查詢輪無槽值 → attempt 不動、不誤 retry
        reg = MagicMock()
        session = _session_with_attempt("套餐六", ["temp", "noodle"], {"flavor": "黑椒"})
        with patch("src.services.container.tool_registry", reg):
            await execute_tags("目前總共 110 元喔～", "現在多少錢", session, "s1")
        assert session["last_failed_attempt"]["missing"] == ["temp", "noodle"]
        reg.add_item.assert_not_called()


class TestQtyChangeFallback:
    """b9-08 回歸：「改成五個好了」LLM 純 prose 不發 SET_QTY"""

    def _cart_one(self, qty=3):
        return [{"item_id": "s1", "itemtype": "snack", "snack": "鮮肉包", "quantity": qty}]

    @pytest.mark.asyncio
    async def test_sole_item_qty_changed(self):
        reg = MagicMock()
        reg.set_item_quantity.return_value = {"ok": True}
        session = {"cart": self._cart_one(3), "llm_history": []}
        with patch("src.services.container.tool_registry", reg):
            await execute_tags("沒問題～改成五個囉", "改成五個好了", session, "s1")
        reg.set_item_quantity.assert_called_once_with(item_id="s1", quantity=5)

    @pytest.mark.asyncio
    async def test_multi_item_cart_unnamed_no_action(self):
        # cart 多品項且 text 沒點名 → 不亂猜
        reg = MagicMock()
        session = {
            "cart": self._cart_one(3)
            + [{"item_id": "s2", "itemtype": "snack", "snack": "豆沙包", "quantity": 2}],
            "llm_history": [],
        }
        with patch("src.services.container.tool_registry", reg):
            await execute_tags("好的～", "改成五個好了", session, "s1")
        reg.set_item_quantity.assert_not_called()

    @pytest.mark.asyncio
    async def test_setqty_tag_turn_no_double(self):
        # LLM 正常發 [SET_QTY] 的輪不重複動作
        reg = MagicMock()
        reg.set_item_quantity.return_value = {"ok": True}
        session = {"cart": self._cart_one(3), "llm_history": []}
        with patch("src.services.container.tool_registry", reg):
            await execute_tags("[SET_QTY:鮮肉包|qty=5]好～", "改成五個好了", session, "s1")
        reg.set_item_quantity.assert_called_once()

    @pytest.mark.asyncio
    async def test_add_more_sentence_untouched(self):
        # 「再加兩個豆沙包」加點句不觸發改量
        reg = MagicMock()
        reg.add_item.return_value = {"ok": True, "item_id": "s2", "message": "已加入"}
        session = {"cart": self._cart_one(5), "llm_history": []}
        with patch("src.services.container.tool_registry", reg):
            await execute_tags("[ADD:豆沙包|qty=2]好～", "再加兩個豆沙包", session, "s1")
        reg.set_item_quantity.assert_not_called()
