# tests/test_side_egg_split.py
# b9-03/b12-09 加荷包蛋拆單：「懷古鹹蛋飯糰 白米 加一顆荷包蛋」LLM 把
# 荷包蛋塞 customization → 獨立點心品項（$15）沒收錢、廚房看不到。
# 主品項入車成功後把客製中的荷包蛋/蔥蛋剝離、拆成獨立 ADD；
# 「加蛋」不碰（飯糰 extra_egg / 蛋餅加蛋是另一語意）

import pytest
from unittest.mock import MagicMock, patch

from src.api.text_tag_executor import execute_tags


def _run_registry():
    from src.dm.dialogue_manager import DialogueManager
    from src.dm.session_store import InMemorySessionStore
    from src.dm.tool_registry import ToolRegistry

    store = InMemorySessionStore()
    dm = DialogueManager(llm=None, store=store)
    tr = ToolRegistry(dm, store)
    return tr, store


@pytest.mark.asyncio
async def test_customization_egg_split_to_item():
    """客製「加一顆荷包蛋」→ 剝離 + 獨立荷包蛋入車，總價含 $15"""
    tr, store = _run_registry()
    sid = "egg-split"
    tr.set_session_id(sid)
    session = store.get(sid)
    session.setdefault("cart", [])
    session["llm_history"] = []
    with patch("src.services.container.tool_registry", tr):
        await execute_tags(
            "[ADD:懷古鹹蛋飯糰|rice=白米|customization=加一顆荷包蛋]好～",
            "一個懷古鹹蛋飯糰 白米 加一顆荷包蛋",
            session,
            sid,
        )
    cart = session["cart"]
    riceball = next(i for i in cart if i.get("itemtype") == "riceball")
    egg = next((i for i in cart if i.get("snack") == "荷包蛋"), None)
    assert egg is not None and egg["quantity"] == 1
    assert "荷包蛋" not in (riceball.get("customization") or "")
    from src.dm import cart_manager

    assert cart_manager.calculate_cart_total(cart) == 80


@pytest.mark.asyncio
async def test_customization_egg_qty_two():
    """「加兩顆荷包蛋」→ 荷包蛋 x2"""
    tr, store = _run_registry()
    sid = "egg-split-2"
    tr.set_session_id(sid)
    session = store.get(sid)
    session.setdefault("cart", [])
    session["llm_history"] = []
    with patch("src.services.container.tool_registry", tr):
        await execute_tags(
            "[ADD:起司蛋餅|customization=加兩顆荷包蛋]好～",
            "一個起司蛋餅 加兩顆荷包蛋",
            session,
            sid,
        )
    egg = next((i for i in session["cart"] if i.get("snack") == "荷包蛋"), None)
    assert egg is not None and egg["quantity"] == 2


@pytest.mark.asyncio
async def test_other_customization_preserved():
    """混合客製「加辣、加一顆荷包蛋」→ 荷包蛋剝離、加辣保留"""
    tr, store = _run_registry()
    sid = "egg-split-3"
    tr.set_session_id(sid)
    session = store.get(sid)
    session.setdefault("cart", [])
    session["llm_history"] = []
    with patch("src.services.container.tool_registry", tr):
        await execute_tags(
            "[ADD:玉米蛋餅|customization=加辣、加一顆荷包蛋]好～",
            "一個玉米蛋餅 加辣 加一顆荷包蛋",
            session,
            sid,
        )
    ep = next(i for i in session["cart"] if i.get("itemtype") == "egg_pancake")
    assert ep.get("customization") == "加辣"
    assert any(i.get("snack") == "荷包蛋" for i in session["cart"])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "neg_cust",
    [
        "不加荷包蛋",
        "不要加荷包蛋",
        "不需要加荷包蛋",
        "不用再加荷包蛋",
        "不想要加荷包蛋",
        "別加荷包蛋",
        "加辣不加荷包蛋",
    ],
)
async def test_negated_egg_not_split(neg_cust):
    """否定語境（含 3 字以上否定詞）不拆單 — 誤拆會反向多收 $15"""
    reg = MagicMock()
    reg.add_item.return_value = {"ok": True, "item_id": "rb_1", "message": "已加入"}
    session = {"cart": [], "llm_history": []}
    with patch("src.services.container.tool_registry", reg):
        await execute_tags(
            f"[ADD:懷古鹹蛋飯糰|rice=白米|customization={neg_cust}]好～",
            f"一個懷古鹹蛋飯糰 白米 {neg_cust}",
            session,
            "s1",
        )
    reg.add_item.assert_called_once_with(name="懷古鹹蛋飯糰", rice="白米", customization=neg_cust)


@pytest.mark.asyncio
async def test_mixed_clause_negation_only_blocks_own_clause():
    """「不要辣、加一顆荷包蛋」否定在別的子句 → 荷包蛋照拆"""
    tr, store = _run_registry()
    sid = "egg-split-clause"
    tr.set_session_id(sid)
    session = store.get(sid)
    session.setdefault("cart", [])
    session["llm_history"] = []
    with patch("src.services.container.tool_registry", tr):
        await execute_tags(
            "[ADD:玉米蛋餅|customization=不要辣、加一顆荷包蛋]好～",
            "一個玉米蛋餅 不要辣 加一顆荷包蛋",
            session,
            sid,
        )
    assert any(i.get("snack") == "荷包蛋" for i in session["cart"])
    ep = next(i for i in session["cart"] if i.get("itemtype") == "egg_pancake")
    assert ep.get("customization") == "不要辣"


@pytest.mark.asyncio
async def test_plain_extra_egg_not_split():
    """「加蛋」不拆（飯糰 extra_egg 語意），customization 原樣保留"""
    reg = MagicMock()
    reg.add_item.return_value = {"ok": True, "item_id": "rb_1", "message": "已加入"}
    session = {"cart": [], "llm_history": []}
    with patch("src.services.container.tool_registry", reg):
        await execute_tags(
            "[ADD:肉鬆飯糰|rice=紫米|customization=加蛋]好～",
            "一個肉鬆飯糰 紫米 加蛋",
            session,
            "s1",
        )
    reg.add_item.assert_called_once_with(name="肉鬆飯糰", rice="紫米", customization="加蛋")
