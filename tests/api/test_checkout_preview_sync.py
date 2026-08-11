"""語音結帳輪回送 checkout_preview 測試

語音答完「內用/外帶」後，前端結帳面板要能預填、不必再選一次。
checkout_step 的 done 事件需帶 preview_result，orchestrator 才會發
checkout_preview 事件（條件：preview_result.get("preview") 為真）。
"""

import pytest
from unittest.mock import MagicMock, patch

from src.api.checkout_handler import CK_DINE, CK_PAY, checkout_step


def _snack_cart():
    return [{"itemtype": "snack", "snack": "薯餅(1片)", "quantity": 1}]


def _done_event(events):
    return next(e for e in events if e["type"] == "done")


@pytest.mark.asyncio
async def test_dine_answered_yields_preview():
    """答外帶 → done 帶 preview_result，前端據此預填面板"""
    store = MagicMock()
    reg = MagicMock()
    session = {"checkout_status": CK_DINE, "cart": _snack_cart(), "llm_history": []}

    with (
        patch("src.services.container.tool_registry", reg),
        patch("src.services.container.session_store", store),
    ):
        events = [e async for e in checkout_step("外帶", "s1", session)]

    preview = _done_event(events)["preview_result"]
    assert preview["preview"] is True
    assert preview["dine_type"] == "take-out"


@pytest.mark.asyncio
async def test_dine_change_in_pay_turn_yields_updated_preview():
    """付款輪改口內用 → preview 跟著更新，面板不會停在舊選項"""
    store = MagicMock()
    reg = MagicMock()
    session = {
        "checkout_status": CK_PAY,
        "checkout_dine_type": "take-out",
        "cart": _snack_cart(),
        "llm_history": [],
    }

    with (
        patch("src.services.container.tool_registry", reg),
        patch("src.services.container.session_store", store),
    ):
        events = [e async for e in checkout_step("啊還是內用好了", "s1", session)]

    assert _done_event(events)["preview_result"]["dine_type"] == "dine-in"


@pytest.mark.asyncio
async def test_pending_pay_carried_into_preview():
    """先講付款還沒答 dine → 該輪無 preview（dine 未知，面板無從預填）"""
    store = MagicMock()
    reg = MagicMock()
    session = {"checkout_status": CK_DINE, "cart": _snack_cart(), "llm_history": []}

    with (
        patch("src.services.container.tool_registry", reg),
        patch("src.services.container.session_store", store),
    ):
        events = [e async for e in checkout_step("刷卡", "s1", session)]

    assert _done_event(events)["preview_result"] is None
    assert session["checkout_pending_pay"] == "line_pay"


@pytest.mark.asyncio
async def test_finalize_turn_has_no_preview():
    """出單輪 → 走 order_complete，不重複送 preview（session 已清 dine_type）"""
    store = MagicMock()
    reg = MagicMock()
    reg.finalize_order.return_value = {"ok": True, "order_number": "01", "total": 30}
    session = {
        "checkout_status": CK_PAY,
        "checkout_dine_type": "take-out",
        "cart": _snack_cart(),
        "llm_history": [],
    }

    with (
        patch("src.services.container.tool_registry", reg),
        patch("src.services.container.session_store", store),
    ):
        events = [e async for e in checkout_step("現金", "s1", session)]

    done = _done_event(events)
    assert done["preview_result"] is None
    assert done["finalize_result"]["order_number"] == "01"
