"""售完硬攔截 + 取消意圖兜底的單元測試。

對應修復：
- Bug 1：售完品項仍被 [ADD] 加入購物車（後端無硬攔截）
- Bug 2：模型說「已取消」但沒發 [REMOVE] tag，購物車沒移除、照樣收錢
"""

import pytest

from src.dm.tool_registry import _sold_out_block
from src.tools.menu import menu_state_service
from src.api.voice_router import _item_mentioned_in_text, _resolve_cancel_intent


@pytest.fixture(autouse=True)
def reset_sold_out():
    """每個測試前後都把售完狀態清乾淨，避免互相污染。"""
    menu_state_service.reset_all_sold_out()
    menu_state_service.clear_cache()
    yield
    menu_state_service.reset_all_sold_out()
    menu_state_service.clear_cache()


# ── Bug 1：售完硬攔截 ──────────────────────────────────────────────


def test_sold_out_block_hits_sold_item():
    """品項設售完 → _sold_out_block 回傳 ok:false 擋下。"""
    menu_state_service.set_item_sold_out("起司蛋餅", True)
    menu_state_service.clear_cache()
    blocked = _sold_out_block("起司蛋餅")
    assert blocked is not None
    assert blocked["ok"] is False
    assert "起司蛋餅" in blocked["message"]


def test_sold_out_block_passes_available_item():
    """未售完品項 → 不擋（回 None）。"""
    assert _sold_out_block("起司蛋餅") is None


def test_sold_out_block_empty_name():
    """空品名不誤擋。"""
    assert _sold_out_block("") is None


# ── Bug 2：取消意圖收斂 ────────────────────────────────────────────

_CART = [
    {"item_id": "a1", "itemtype": "riceball", "rice": "紫米", "flavor": "鮪魚飯糰"},
    {"item_id": "b2", "itemtype": "drink", "drink": "精選紅茶", "size": "中杯", "temp": "冰"},
]


def test_cancel_named_riceball():
    """「飯糰不要了」→ 對應到飯糰那一項。"""
    assert _resolve_cancel_intent("飯糰不要了", _CART) == ["a1"]


def test_cancel_named_drink():
    """「紅茶不要了」→ 對應到紅茶（精選紅茶 尾字匹配）。"""
    assert _resolve_cancel_intent("紅茶不要了", _CART) == ["b2"]


def test_cancel_all():
    """「全部不要了」→ 整單取消。"""
    assert _resolve_cancel_intent("全部不要了", _CART) == ["__all__"]


def test_no_misfire_on_spicy_preference():
    """關鍵安全案例：「飯糰不要辣」是加料偏好，不可誤判成取消飯糰。"""
    assert _resolve_cancel_intent("飯糰不要辣", _CART) == []


def test_no_misfire_on_cilantro():
    """「不要香菜」不含終結性取消詞，不觸發移除。"""
    assert _resolve_cancel_intent("不要香菜", _CART) == []


def test_no_cancel_intent_plain_order():
    """單純點餐句不觸發移除。"""
    assert _resolve_cancel_intent("我要一個飯糰", _CART) == []


def test_empty_cart_no_match():
    """空購物車不觸發。"""
    assert _resolve_cancel_intent("飯糰不要了", []) == []


def test_item_mentioned_tail_match():
    """尾字類別名詞比對：句子提到「飯糰」對應到「紫米·鮪魚飯糰」。"""
    assert _item_mentioned_in_text(_CART[0], "那個飯糰拿掉") is True
    assert _item_mentioned_in_text(_CART[1], "那個飯糰拿掉") is False
