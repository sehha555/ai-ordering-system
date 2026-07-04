"""text_tag_executor 複合單句結帳推進測試

驗證 [CHECKOUT] 攔截後，同句帶內用外帶/付款資訊時直接推進結帳狀態機，
不需要等下一輪重問（fail case：「大杯冰豆漿 結帳 外帶 現金」意圖被吞）。

Mock 策略：container.tool_registry 換成 MagicMock，聚焦 execute_tags 的分派邏輯。
"""

import pytest
from unittest.mock import MagicMock, patch

from src.api.checkout_handler import CK_DINE, CK_PAY
from src.api.text_tag_executor import execute_tags


def _make_session(cart=None):
    return {
        "cart": cart if cart is not None else [],
        "llm_history": [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "raw"},
        ],
    }


def _make_registry(cart_after_add=None, order_number="01"):
    """建立 mock tool_registry：add_item 成功並模擬品項入車，finalize_order 成功出單。"""
    registry = MagicMock()
    registry.add_item.return_value = {
        "ok": True,
        "item_id": "i1",
        "message": "已加入豆漿",
    }
    registry.finalize_order.return_value = {
        "ok": True,
        "order_number": order_number,
        "total": 90,
    }
    return registry


@pytest.fixture
def registry():
    reg = _make_registry()
    with patch("src.services.container.tool_registry", reg):
        yield reg


@pytest.mark.asyncio
async def test_checkout_with_dine_and_payment_finalizes(registry):
    """同句帶外帶+現金 → 直接 finalize，回覆帶單號"""
    cart = [{"itemtype": "snack", "snack": "薯餅(1片)", "quantity": 1}]
    session = _make_session(cart)

    result = await execute_tags("[CHECKOUT]好～", "結帳 外帶 現金", session, "s1")

    registry.finalize_order.assert_called_once_with(dine_type="take-out", payment_method="cash")
    assert result.finalize_result["order_number"] == "01"
    assert "01號" in result.full_text
    assert "checkout_status" not in session


@pytest.mark.asyncio
async def test_checkout_with_dine_only_advances_to_pay(registry):
    """同句只帶外帶 → 進 CK_PAY 問付款方式"""
    cart = [{"itemtype": "snack", "snack": "薯餅(1片)", "quantity": 1}]
    session = _make_session(cart)

    result = await execute_tags("[CHECKOUT]好～", "結帳 外帶", session, "s1")

    registry.finalize_order.assert_not_called()
    assert session["checkout_status"] == CK_PAY
    assert session["checkout_dine_type"] == "take-out"
    assert "現金" in result.full_text
    assert result.finalize_result is None


@pytest.mark.asyncio
async def test_checkout_without_dine_stays_in_dine_state(registry):
    """同句沒帶內用外帶 → 維持 CK_DINE（既有行為，下輪狀態機接手）"""
    cart = [{"itemtype": "snack", "snack": "薯餅(1片)", "quantity": 1}]
    session = _make_session(cart)

    result = await execute_tags("[CHECKOUT]內用還是外帶？", "結帳", session, "s1")

    registry.finalize_order.assert_not_called()
    assert session["checkout_status"] == CK_DINE
    assert result.finalize_result is None


@pytest.mark.asyncio
async def test_compound_add_and_checkout_adds_before_finalize(registry):
    """複合句 [ADD][CHECKOUT] → 先 add_item 再 finalize（品項不漏單）"""
    cart = [{"itemtype": "snack", "snack": "薯餅(1片)", "quantity": 1}]
    session = _make_session(cart)

    result = await execute_tags(
        "[ADD:豆漿|size=大杯|temp=冰][CHECKOUT]好～",
        "再一杯大杯冰豆漿 結帳 外帶 現金",
        session,
        "s1",
    )

    registry.add_item.assert_called_once()
    registry.finalize_order.assert_called_once_with(dine_type="take-out", payment_method="cash")
    assert result.finalize_result is not None
    # add_item 必須先於 finalize_order（品項先入車才結帳）
    call_names = [c[0] for c in registry.mock_calls]
    assert call_names.index("add_item") < call_names.index("finalize_order")


@pytest.mark.asyncio
async def test_empty_cart_with_compound_add_checkout_enters_checkout(registry):
    """空車但同句帶 [ADD] → 不回「購物車是空的」，照常進結帳"""
    session = _make_session(cart=[])

    result = await execute_tags(
        "[ADD:豆漿|size=大杯|temp=冰][CHECKOUT]好～",
        "一杯大杯冰豆漿 外帶 現金 結帳",
        session,
        "s1",
    )

    assert "空的" not in result.full_text
    registry.add_item.assert_called_once()


@pytest.mark.asyncio
async def test_empty_cart_checkout_without_add_rejected(registry):
    """空車純結帳 → 仍回「購物車是空的」，不進結帳"""
    session = _make_session(cart=[])

    result = await execute_tags("[CHECKOUT]好～", "結帳 外帶 現金", session, "s1")

    registry.finalize_order.assert_not_called()
    assert "空的" in result.full_text
    assert "checkout_status" not in session


@pytest.mark.asyncio
async def test_add_failed_skips_advance(registry):
    """ADD 補槽失敗（缺欄位）→ 不推進 finalize，讓追問先走"""
    registry.add_item.return_value = {
        "ok": False,
        "missing": ["rice"],
        "message": "飯糰要紫米白米？",
    }
    cart = [{"itemtype": "snack", "snack": "薯餅(1片)", "quantity": 1}]
    session = _make_session(cart)

    result = await execute_tags(
        "[ADD:鮪魚飯糰][CHECKOUT]好～",
        "一個鮪魚飯糰 結帳 外帶 現金",
        session,
        "s1",
    )

    registry.finalize_order.assert_not_called()
    assert session["checkout_status"] == CK_DINE
    assert result.finalize_result is None


@pytest.mark.asyncio
async def test_pending_cart_finalizes_as_pending(registry):
    """cart 有客製待確認品項 + 同句外帶 → 直接建「待店員結算」單"""
    cart = [{"itemtype": "riceball", "flavor": "鮪魚", "customization": "加很多料", "quantity": 1}]
    session = _make_session(cart)

    with patch("src.dm.cart_manager.cart_has_pending", return_value=True):
        result = await execute_tags("[CHECKOUT]好～", "結帳 外帶 現金", session, "s1")

    registry.finalize_order.assert_called_once_with(dine_type="take-out", payment_method="pending")
    assert result.finalize_result is not None
    assert "店員確認" in result.full_text
    assert "checkout_status" not in session
