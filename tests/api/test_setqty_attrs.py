# tests/api/test_setqty_attrs.py
# SET_QTY 屬性擴充：LLM 表達「換大杯/改溫的」慣性發 [SET_QTY:品項|size=大杯]
# （b6-07：size 被丟 + qty 缺省重設，話術說換好了但 cart 沒動）

import pytest
from unittest.mock import MagicMock, patch

from src.api.tag_parser import parse_set_qty_tag
from src.api.text_tag_executor import execute_tags
from src.dm.tool_registry import ToolRegistry
from src.dm.dialogue_manager import DialogueManager
from src.dm.session_store import InMemorySessionStore


class TestParseSetQtyTag:
    def test_qty_only(self):
        assert parse_set_qty_tag("薯餅|qty=2") == ("薯餅", 2, {})

    def test_size_only_qty_is_none(self):
        # qty 沒給必須回 None：預設 1 會把「三杯紅茶」重設成一杯
        name, qty, attrs = parse_set_qty_tag("精選紅茶|size=大杯")
        assert (name, qty, attrs) == ("精選紅茶", None, {"size": "大杯"})

    def test_qty_and_attrs_combined(self):
        name, qty, attrs = parse_set_qty_tag("紅茶|qty=2|size=大杯|temp=溫")
        assert (name, qty, attrs) == ("紅茶", 2, {"size": "大杯", "temp": "溫"})

    def test_bare_name(self):
        assert parse_set_qty_tag("薯餅") == ("薯餅", None, {})


@pytest.fixture
def real_registry():
    store = InMemorySessionStore()
    dm = DialogueManager(llm=None, store=store)
    tr = ToolRegistry(dm, store)
    tr.set_session_id("attr-test")
    return tr, store


class TestSetItemAttrs:
    def test_drink_size_swap_preserves_qty(self, real_registry):
        tr, store = real_registry
        tr.add_item(name="精選紅茶", size="中杯", temp="冰", quantity=3)
        item = store.get("attr-test")["cart"][0]
        result = tr.set_item_attrs(item_id=item["item_id"], size="大杯")
        assert result["ok"]
        assert item["size"] == "大杯"
        assert item["quantity"] == 3

    def test_drink_temp_swap(self, real_registry):
        tr, store = real_registry
        tr.add_item(name="有糖豆漿", size="中杯", temp="冰")
        item = store.get("attr-test")["cart"][0]
        result = tr.set_item_attrs(item_id=item["item_id"], temp="溫")
        assert result["ok"]
        assert item["temp"] == "溫"

    def test_non_drink_size_rejected(self, real_registry):
        tr, store = real_registry
        tr.add_item(name="薯餅(1片)")
        item = store.get("attr-test")["cart"][0]
        result = tr.set_item_attrs(item_id=item["item_id"], size="大杯")
        assert not result["ok"]
        assert item.get("size") is None


def _drink_session(qty=3):
    return {
        "cart": [
            {
                "itemtype": "drink",
                "drink": "精選紅茶",
                "size": "中杯",
                "temp": "冰",
                "quantity": qty,
                "item_id": "drink_1",
            }
        ],
        "llm_history": [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "raw"},
        ],
    }


@pytest.mark.asyncio
async def test_setqty_with_size_dispatches_attrs_not_qty():
    """[SET_QTY:紅茶|size=大杯] → set_item_attrs，且不動數量（b6-07 主場景）"""
    reg = MagicMock()
    reg.set_item_attrs.return_value = {"ok": True, "message": "已把精選紅茶換成大杯"}
    session = _drink_session(qty=3)
    with patch("src.services.container.tool_registry", reg):
        await execute_tags(
            "[SET_QTY:精選紅茶|size=大杯]好，紅茶換成大杯囉～", "紅茶換大杯", session, "s1"
        )
    reg.set_item_attrs.assert_called_once_with(item_id="drink_1", size="大杯")
    reg.set_item_quantity.assert_not_called()


@pytest.mark.asyncio
async def test_setqty_with_qty_and_size_applies_both():
    reg = MagicMock()
    reg.set_item_quantity.return_value = {"ok": True, "message": "數量 3 → 2"}
    reg.set_item_attrs.return_value = {"ok": True, "message": "已把精選紅茶換成大杯"}
    session = _drink_session(qty=3)
    with patch("src.services.container.tool_registry", reg):
        await execute_tags(
            "[SET_QTY:精選紅茶|qty=2|size=大杯]好～", "紅茶改兩杯大杯", session, "s1"
        )
    reg.set_item_quantity.assert_called_once_with(item_id="drink_1", quantity=2)
    reg.set_item_attrs.assert_called_once_with(item_id="drink_1", size="大杯")


@pytest.mark.asyncio
async def test_remove_add_swap_inherits_qty_and_temp():
    """「三杯紅茶換大杯」LLM 走 REMOVE+ADD → ADD 繼承數量與 temp，不重設成 x1"""
    reg = MagicMock()
    reg.remove_from_cart.return_value = {"ok": True, "message": "已移除"}
    reg.add_item.return_value = {"ok": True, "item_id": "drink_2", "message": "已加入"}
    session = _drink_session(qty=3)
    with patch("src.services.container.tool_registry", reg):
        await execute_tags(
            "[REMOVE:精選紅茶][ADD:精選紅茶|size=大杯]好，換成大杯囉～",
            "紅茶換大杯",
            session,
            "s1",
        )
    reg.add_item.assert_called_once_with(name="精選紅茶", size="大杯", quantity=3, temp="冰")


@pytest.mark.asyncio
async def test_remove_add_different_item_no_inherit():
    """「紅茶換豆漿」跨品項換 → 不繼承（數量/溫度意圖不明，寧可追問）"""
    reg = MagicMock()
    reg.remove_from_cart.return_value = {"ok": True, "message": "已移除"}
    reg.add_item.return_value = {"ok": True, "item_id": "drink_2", "message": "已加入"}
    session = _drink_session(qty=3)
    with patch("src.services.container.tool_registry", reg):
        await execute_tags(
            "[REMOVE:精選紅茶][ADD:有糖豆漿|size=中杯]好～",
            "紅茶換豆漿 中杯",
            session,
            "s1",
        )
    reg.add_item.assert_called_once_with(name="有糖豆漿", size="中杯")


@pytest.mark.asyncio
async def test_add_without_remove_no_inherit():
    """單純加點（無 REMOVE）不觸發繼承"""
    reg = MagicMock()
    reg.add_item.return_value = {"ok": True, "item_id": "drink_3", "message": "已加入"}
    session = _drink_session(qty=3)
    with patch("src.services.container.tool_registry", reg):
        await execute_tags(
            "[ADD:精選紅茶|size=大杯|temp=冰]好～", "再一杯大杯冰紅茶", session, "s1"
        )
    reg.add_item.assert_called_once_with(name="精選紅茶", size="大杯", temp="冰")


@pytest.mark.asyncio
async def test_setqty_qty_only_unchanged_behavior():
    """既有 [SET_QTY:品項|qty=N] 路徑不受擴充影響"""
    reg = MagicMock()
    reg.set_item_quantity.return_value = {"ok": True, "message": "數量 3 → 1"}
    session = _drink_session(qty=3)
    with patch("src.services.container.tool_registry", reg):
        await execute_tags("[SET_QTY:精選紅茶|qty=1]好～", "紅茶一杯就好", session, "s1")
    reg.set_item_quantity.assert_called_once_with(item_id="drink_1", quantity=1)
    reg.set_item_attrs.assert_not_called()
