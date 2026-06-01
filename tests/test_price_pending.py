"""客製化價格待確認偵測的單元測試（price_pending 核心）。

對應需求：加料類客製 → 價格待確認 + 不能先付；
免費標準選項（辣菜脯）與純減料偏好 → 不誤標。
"""

import pytest

from src.dm.cart_manager import (
    cart_has_pending,
    is_item_price_pending,
    is_price_pending_customization,
)


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
