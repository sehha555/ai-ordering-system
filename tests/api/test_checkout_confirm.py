"""結帳確認話術測試

驗證進結帳第一問複述品項+總金額（build_checkout_confirm），
以及 finalize 成功報號時帶總金額（同句直接出單路徑沒經過第一問）。
"""

import pytest
from unittest.mock import MagicMock, patch

from src.api.checkout_handler import build_checkout_confirm, finalize_and_reply
from src.dm.cart_manager import calculate_cart_total


def _riceball_item(flavor="源味傳統", rice="紫米", quantity=1):
    return {"itemtype": "riceball", "flavor": flavor, "rice": rice, "quantity": quantity}


# ---------- build_checkout_confirm ----------


def test_confirm_contains_items_and_total():
    """一般 cart → 確認句含品項名、總金額、內用外帶問句"""
    cart = [_riceball_item(quantity=2)]
    total = calculate_cart_total(cart)
    assert total > 0

    msg = build_checkout_confirm(cart)

    assert "跟您確認" in msg
    assert "源味傳統" in msg
    assert f"共{total}元" in msg
    assert "內用還是外帶" in msg


def test_confirm_pending_cart_no_total():
    """有客製待確認品項 → 不報總金額，改說待店員確認"""
    cart = [_riceball_item()]

    with patch("src.dm.cart_manager.cart_has_pending", return_value=True):
        msg = build_checkout_confirm(cart)

    assert "店員確認" in msg
    assert "元" not in msg
    assert "內用還是外帶" in msg


# ---------- finalize_and_reply 金額話術 ----------


@pytest.fixture
def registry():
    reg = MagicMock()
    reg.finalize_order.return_value = {"ok": True, "order_number": "01", "total": 90}
    return reg


def test_finalize_reply_contains_total(registry):
    """finalize 成功 → 報號帶總金額"""
    session = {"checkout_status": "CHECKOUT_PAY", "checkout_dine_type": "take-out"}

    reply, result = finalize_and_reply("take-out", "cash", session, registry)

    assert "01號" in reply
    assert "共90元" in reply
    assert result["total"] == 90
    assert "checkout_status" not in session


def test_finalize_pending_reply_no_total(registry):
    """pending 單 → 維持待店員結算話術，不報金額"""
    session = {}

    reply, _ = finalize_and_reply("take-out", "pending", session, registry)

    assert "店員確認" in reply
    assert "90元" not in reply
