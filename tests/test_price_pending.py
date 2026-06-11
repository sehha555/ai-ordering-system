"""客製化價格待確認偵測的單元測試（price_pending 核心）。

對應需求：飯糰表內加料（起司等）→ 精準加價不待確認；
辣菜脯免費正常算；表外/未知加料才待確認 + 不能先付；
純減料偏好 → 不誤標。
"""

import pytest

from src.dm.cart_manager import (
    cart_has_pending,
    get_price_info,
    is_item_price_pending,
    is_price_pending_customization,
)
from src.tools.riceball_tool import menu_tool


@pytest.mark.parametrize(
    "customization,expected",
    [
        # 加價加料 → 待確認
        ("加起司", True),
        ("換醬", True),
        ("加鵝肝", True),
        ("多一份肉", True),
        # 免費標準辣度（模型對「要辣」輸出的字串）→ 不待確認
        ("加辣菜脯", False),
        ("加辣", False),
        ("辣菜脯", False),
        # 純減料偏好 → 不待確認
        ("不要辣", False),
        ("不要香菜", False),
        ("不加蛋", False),  # 「不加」是減料，不是加料
        ("去掉小黃瓜", False),
        # 無客製
        ("", False),
        (None, False),
    ],
)
def test_is_price_pending_customization(customization, expected):
    assert is_price_pending_customization(customization) is expected


def test_is_item_price_pending_from_field():
    """由 item 的 customization 欄位推導。"""
    assert is_item_price_pending({"customization": "加起司"}) is True
    assert is_item_price_pending({"customization": "加辣菜脯"}) is False
    assert is_item_price_pending({}) is False


def test_cart_has_pending():
    """購物車任一品項待確認 → True。"""
    cart = [
        {"item_id": "a", "customization": "加辣菜脯"},  # 免費
        {"item_id": "b"},  # 無客製
    ]
    assert cart_has_pending(cart) is False
    cart.append({"item_id": "c", "customization": "加起司"})  # 加價加料
    assert cart_has_pending(cart) is True
    assert cart_has_pending([]) is False


def _riceball(customization=None, **kw):
    item = {"itemtype": "riceball", "flavor": "源味傳統", "rice": "紫米", "quantity": 1}
    if customization:
        item["customization"] = customization
    item.update(kw)
    return item


def _base_price(**kw):
    return menu_tool.quote_riceball_price(flavor="源味傳統", **kw)["total_price"]


@pytest.mark.parametrize(
    "customization,expected_pending,expected_addon",
    [
        # 表內加料 → 精準加價、不待確認
        ("加起司", False, 10),
        ("加起司片", False, 10),
        ("加鮪魚", False, 35),
        ("加起司不要油條", False, 10),  # 混合：加料計價、減料不影響
        # 免費辣度 → 不加價、不待確認
        ("加辣菜脯", False, 0),
        # 表外/未知加料訊號 → 待確認、維持基礎價
        ("加香菜", True, None),
        ("換醬", True, None),
        ("多一份肉", True, None),
    ],
)
def test_riceball_addon_precise_pricing(customization, expected_pending, expected_addon):
    """飯糰表內加料自動算進單品價；表外才標 price_pending。"""
    item = _riceball(customization)
    assert is_item_price_pending(item) is expected_pending
    pi = get_price_info(item)
    assert pi["ok"] is True
    expected_total = _base_price() + (expected_addon or 0)
    assert pi["total_price"] == expected_total


def test_riceball_egg_addon_not_double_charged():
    """extra_egg 欄位已加價時，customization「加蛋」不重複計。"""
    item = _riceball("加蛋", extra_egg=True)
    assert is_item_price_pending(item) is False
    assert get_price_info(item)["total_price"] == _base_price(extra_egg=True)


def test_riceball_egg_addon_via_customization_only():
    """只在 customization 說「加蛋」→ 走加料表 +10。"""
    item = _riceball("加蛋")
    assert is_item_price_pending(item) is False
    assert get_price_info(item)["total_price"] == _base_price() + 10


def test_non_riceball_addon_stays_pending():
    """非飯糰品項無加料表，加料客製維持待確認粗判。"""
    item = {"itemtype": "egg_pancake", "flavor": "原味", "customization": "加起司"}
    assert is_item_price_pending(item) is True
