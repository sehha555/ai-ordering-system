# -*- coding: utf-8 -*-
"""b11 批次修復 regression

- b11-05 tag 洩漏：customization 值含頓號，句切在 tag 內腰斬 → 殘片 strip 不掉洩漏給 TTS
- b11-03 減量誤全移除：「紅茶一杯就好」LLM 發 [REMOVE:紅茶] 整項蒸發
- b11-02 CK_PAY dine 改口：「啊還是外帶好了」被吃，單照舊 dine_type 出
"""

import pytest
from unittest.mock import MagicMock, patch

from src.api.checkout_handler import CK_PAY
from src.api.text_tag_executor import execute_tags
from src.services.llm_tool_caller import _punct_outside_tag


def _make_session(cart=None):
    return {
        "cart": cart if cart is not None else [],
        "llm_history": [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "raw"},
        ],
    }


class TestPunctOutsideTag:
    """b11-05：句切不可腰斬未閉合 [tag]"""

    def test_punct_inside_tag_not_splittable(self):
        buf = "[ADD:原味蛋餅|customization=不要蔥、"
        assert not _punct_outside_tag(buf, len(buf) - 1)

    def test_punct_after_closed_tag_splittable(self):
        buf = "[ADD:原味蛋餅|customization=不要蔥]好，"
        assert _punct_outside_tag(buf, len(buf) - 1)

    def test_plain_text_splittable(self):
        buf = "好的，"
        assert _punct_outside_tag(buf, len(buf) - 1)

    def test_second_tag_open(self):
        buf = "[ADD:a]好～[ADD:紅茶|customization=去冰、"
        assert not _punct_outside_tag(buf, len(buf) - 1)


class TestKeepQtyFallback:
    """b11-03：「N杯就好」減量兜底"""

    def _drink(self, qty=3):
        return {
            "item_id": "drink_1",
            "itemtype": "drink",
            "drink": "精選紅茶",
            "size": "中杯",
            "temp": "冰",
            "quantity": qty,
        }

    @pytest.mark.asyncio
    async def test_remove_only_restores_with_kept_qty(self):
        # [REMOVE:紅茶] 單發 → 快照回復 x1
        session = _make_session([self._drink(3)])
        reg = MagicMock()

        def _remove(item_id=None, **kw):
            session["cart"] = [i for i in session["cart"] if i.get("item_id") != item_id]
            return {"ok": True, "message": "已移除"}

        reg.remove_from_cart.side_effect = _remove
        with patch("src.services.container.tool_registry", reg):
            await execute_tags("[REMOVE:紅茶]好的～", "紅茶一杯就好", session, "s1")
        cart = session["cart"]
        assert len(cart) == 1
        assert cart[0]["drink"] == "精選紅茶"
        assert cart[0]["quantity"] == 1

    @pytest.mark.asyncio
    async def test_no_tag_prose_sets_qty(self):
        # 純 prose 無 tag → text 點名品項直接改量
        session = _make_session([self._drink(3)])
        reg = MagicMock()
        reg.set_item_quantity.return_value = {"ok": True}
        with patch("src.services.container.tool_registry", reg):
            await execute_tags("沒問題，紅茶改成一杯囉～", "紅茶一杯就好", session, "s1")
        reg.set_item_quantity.assert_called_once_with(item_id="drink_1", quantity=1)

    @pytest.mark.asyncio
    async def test_remove_add_pair_no_double_restore(self):
        # REMOVE+ADD 重建（LLM 正確發法）→ 不重複回復
        session = _make_session([self._drink(3)])
        reg = MagicMock()

        def _remove(item_id=None, **kw):
            session["cart"] = [i for i in session["cart"] if i.get("item_id") != item_id]
            return {"ok": True, "message": "已移除"}

        def _add(**kw):
            session["cart"].append(
                {"item_id": "drink_2", "itemtype": "drink", "drink": "精選紅茶", "quantity": 1}
            )
            return {"ok": True, "item_id": "drink_2", "message": "已加入"}

        reg.remove_from_cart.side_effect = _remove
        reg.add_item.side_effect = _add
        with patch("src.services.container.tool_registry", reg):
            await execute_tags(
                "[REMOVE:紅茶][ADD:紅茶|size=中杯|temp=冰]好～", "紅茶一杯就好", session, "s1"
            )
        drinks = [i for i in session["cart"] if i.get("itemtype") == "drink"]
        assert len(drinks) == 1
        assert drinks[0]["quantity"] == 1

    @pytest.mark.asyncio
    async def test_order_sentence_not_affected(self):
        # 「給我一杯就好」新點單語境（車上無品項被點名）→ 不觸發改量
        session = _make_session([self._drink(3)])
        reg = MagicMock()
        with patch("src.services.container.tool_registry", reg):
            await execute_tags("好的～", "給我一杯就好", session, "s1")
        reg.set_item_quantity.assert_not_called()


class TestCkPayDineChange:
    """b11-02：CK_PAY 付款輪改口內用外帶"""

    @pytest.mark.asyncio
    async def test_dine_change_updates_and_acknowledges(self):
        from src.api.checkout_handler import checkout_step

        store = MagicMock()
        reg = MagicMock()
        session = {
            "checkout_status": CK_PAY,
            "checkout_dine_type": "dine-in",
            "cart": [{"itemtype": "snack", "snack": "薯餅(1片)", "quantity": 1}],
            "llm_history": [],
        }
        with (
            patch("src.services.container.tool_registry", reg),
            patch("src.services.container.session_store", store),
        ):
            events = [e async for e in checkout_step("啊還是外帶好了", "s1", session)]
        assert session["checkout_dine_type"] == "take-out"
        assert "外帶" in events[0]["content"]
        assert session["checkout_status"] == CK_PAY  # 仍等付款

    @pytest.mark.asyncio
    async def test_dine_change_with_payment_finalizes_new_dine(self):
        from src.api.checkout_handler import checkout_step

        store = MagicMock()
        reg = MagicMock()
        reg.finalize_order.return_value = {"ok": True, "order_number": "01", "total": 20}
        session = {
            "checkout_status": CK_PAY,
            "checkout_dine_type": "dine-in",
            "cart": [{"itemtype": "snack", "snack": "薯餅(1片)", "quantity": 1}],
            "llm_history": [],
        }
        with (
            patch("src.services.container.tool_registry", reg),
            patch("src.services.container.session_store", store),
        ):
            _ = [e async for e in checkout_step("外帶 現金", "s1", session)]
        reg.finalize_order.assert_called_once_with(dine_type="take-out", payment_method="cash")

    @pytest.mark.asyncio
    async def test_dine_word_with_order_intent_falls_through(self):
        # PR #30 review 問題 1：「外帶 再加一個蛋餅」加點意圖優先，
        # 必須 exit_checkout fallthrough 給 LLM，不可被改口 acknowledge 吞掉
        from src.api.checkout_handler import checkout_step

        store = MagicMock()
        reg = MagicMock()
        session = {
            "checkout_status": CK_PAY,
            "checkout_dine_type": "dine-in",
            "cart": [{"itemtype": "snack", "snack": "薯餅(1片)", "quantity": 1}],
            "llm_history": [],
        }
        with (
            patch("src.services.container.tool_registry", reg),
            patch("src.services.container.session_store", store),
        ):
            events = [e async for e in checkout_step("外帶 再加一個蛋餅", "s1", session)]
        assert events == []  # 未 yield = fallthrough 給 LLM
        assert "checkout_status" not in session  # 已退出結帳狀態


class TestPendingAttemptAbandon:
    """b11-09：pending 追問棄答 — 客人答結帳問題不理 attempt 追問 → 放掉接回結帳"""

    def _session(self):
        return {
            "cart": [
                {
                    "item_id": "ep_1",
                    "itemtype": "egg_pancake",
                    "flavor": "起司",
                    "quantity": 1,
                }
            ],
            "llm_history": [
                {"role": "user", "content": "結帳"},
                {"role": "assistant", "content": "飯糰要白米紫米還是混米？"},
            ],
            "pending_checkout": True,
            "last_failed_attempt": {
                "item_name": "QQ滷蛋飯糰",
                "missing": ["rice"],
                "provided": {},
                "message": "飯糰要白米紫米還是混米？",
            },
        }

    @pytest.mark.asyncio
    async def test_dine_answer_abandons_attempt_and_resumes_checkout(self):
        """「外帶」→ attempt 清空、同句推進到 CK_PAY 問付款"""
        reg = MagicMock()
        session = self._session()
        with patch("src.services.container.tool_registry", reg):
            await execute_tags("好的～", "外帶", session, "s1")
        assert session.get("last_failed_attempt") is None
        assert session.get("checkout_status") == CK_PAY

    @pytest.mark.asyncio
    async def test_slot_answer_not_abandoned(self):
        """補槽回答「紫米」→ attempt 不被放掉（照走補槽 retry）"""
        reg = MagicMock()
        reg.add_item.return_value = {"ok": True, "item_id": "rb_1", "message": "已加入"}
        session = self._session()
        with patch("src.services.container.tool_registry", reg):
            await execute_tags(
                "[ADD:QQ滷蛋飯糰|rice=紫米]好～",
                "紫米",
                session,
                "s1",
            )
        # 補槽成功 → attempt 清空是「補齊」路徑而非棄答路徑，add_item 有被呼叫
        reg.add_item.assert_called_once()

    @pytest.mark.asyncio
    async def test_dine_with_new_order_not_resumed(self):
        """「外帶 再一個蛋餅」有新 ADD → 改口加點路徑：不走棄答搶跑結帳
        （attempt 由 any_ok 既有路徑清除，結帳意圖放掉回一般流程）"""
        reg = MagicMock()
        reg.add_item.return_value = {"ok": True, "item_id": "ep_2", "message": "已加入"}
        session = self._session()
        with patch("src.services.container.tool_registry", reg):
            await execute_tags(
                "[ADD:玉米蛋餅]好～",
                "外帶 再一個玉米蛋餅",
                session,
                "s1",
            )
        assert session.get("checkout_status") != CK_PAY
