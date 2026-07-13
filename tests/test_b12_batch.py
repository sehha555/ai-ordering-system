# -*- coding: utf-8 -*-
"""b12 批次修復 regression

- b12-02 結帳 dine/pay 跨輪丟失：首輪「外帶」被忘結帳重問；CK_DINE 收「刷卡」卡住
- b12-05 混合飲品拆解：「三杯紅茶+豆漿」被拆成 紅茶x3 + 豆漿x1（多收 $20 廚房做錯）
- b12-07 跨品項替換：「換成無骨雞排蛋堡」LLM 只發 ADD 沒發 REMOVE，兩個漢堡都在車
"""

import pytest
from unittest.mock import MagicMock, patch

from src.api.checkout_handler import CK_DINE, CK_PAY, checkout_step
from src.api.text_tag_executor import execute_tags


def _make_session(cart=None, **extra):
    s = {
        "cart": cart if cart is not None else [],
        "llm_history": [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "raw"},
        ],
    }
    s.update(extra)
    return s


class TestDinePayCrossTurn:
    """b12-02：dine hint 與 pending pay 跨輪記憶"""

    @pytest.mark.asyncio
    async def test_dine_hint_recorded_on_add_turn(self):
        reg = MagicMock()
        reg.add_item.return_value = {"ok": True, "item_id": "i1", "message": "已加入"}
        session = _make_session()
        with patch("src.services.container.tool_registry", reg):
            await execute_tags("[ADD:起司蛋吐司]好～", "起司蛋吐司一份 外帶", session, "s1")
        assert session.get("dine_type_hint") == "take-out"

    @pytest.mark.asyncio
    async def test_checkout_uses_hint_skips_dine_question(self):
        # 進結帳時有 hint → 不重問內用外帶，直接進 CK_PAY 並複述外帶
        reg = MagicMock()
        cart = [{"itemtype": "snack", "snack": "薯餅(1片)", "quantity": 1}]
        session = _make_session(cart, dine_type_hint="take-out")
        with patch("src.services.container.tool_registry", reg):
            result = await execute_tags("[CHECKOUT]好～", "結帳", session, "s1")
        assert session["checkout_status"] == CK_PAY
        assert session["checkout_dine_type"] == "take-out"
        assert "外帶" in result.full_text
        assert "dine_type_hint" not in session  # 用過即棄

    @pytest.mark.asyncio
    async def test_ck_dine_pay_word_remembered(self):
        # CK_DINE 收到「刷卡」→ 記住，答 dine 後直接出單
        store = MagicMock()
        reg = MagicMock()
        reg.finalize_order.return_value = {"ok": True, "order_number": "01", "total": 20}
        session = {
            "checkout_status": CK_DINE,
            "cart": [{"itemtype": "snack", "snack": "薯餅(1片)", "quantity": 1}],
            "llm_history": [],
        }
        with (
            patch("src.services.container.tool_registry", reg),
            patch("src.services.container.session_store", store),
        ):
            events1 = [e async for e in checkout_step("刷卡", "s1", session)]
            assert "內用還是外帶" in events1[0]["content"]
            assert session["checkout_pending_pay"] == "line_pay"
            _ = [e async for e in checkout_step("內用", "s1", session)]
        reg.finalize_order.assert_called_once_with(dine_type="dine-in", payment_method="line_pay")

    @pytest.mark.asyncio
    async def test_ck_dine_plain_answer_unaffected(self):
        # 無 pending pay 的正常流程不變：答內用 → 進 CK_PAY 問付款
        store = MagicMock()
        reg = MagicMock()
        session = {
            "checkout_status": CK_DINE,
            "cart": [{"itemtype": "snack", "snack": "薯餅(1片)", "quantity": 1}],
            "llm_history": [],
        }
        with (
            patch("src.services.container.tool_registry", reg),
            patch("src.services.container.session_store", store),
        ):
            _ = [e async for e in checkout_step("內用", "s1", session)]
        assert session["checkout_status"] == CK_PAY
        reg.finalize_order.assert_not_called()


class TestMixedDrinkMerge:
    """b12-05：混合飲品合併"""

    @pytest.mark.asyncio
    async def test_split_mixed_drink_merged(self):
        # LLM 拆成 紅茶x3 + 豆漿x1 → 合併成 紅茶+豆漿 x3
        session = _make_session()
        reg = MagicMock()
        ids = iter(["drink_1", "drink_2"])

        def _add(**kw):
            iid = next(ids)
            item = {
                "item_id": iid,
                "itemtype": "drink",
                "drink": "精選紅茶" if iid == "drink_1" else "有糖豆漿",
                "size": "中杯",
                "temp": "冰",
                "quantity": 3 if iid == "drink_1" else 1,
            }
            session["cart"].append(item)
            return {"ok": True, "item_id": iid, "message": "已加入"}

        reg.add_item.side_effect = _add
        reg.add_drink.return_value = {"ok": True, "item_id": "drink_3", "message": "已加入"}
        with patch("src.services.container.tool_registry", reg):
            await execute_tags(
                "[ADD:紅茶|size=中|temp=冰|qty=3][ADD:豆漿|size=中|temp=冰]好～",
                "三杯中杯冰紅茶+豆漿",
                session,
                "s1",
            )
        # 兩個單品被移除、改加混合品項 x3
        assert all(i.get("item_id") not in ("drink_1", "drink_2") for i in session["cart"])
        reg.add_drink.assert_called_once_with(
            flavor="紅茶+豆漿", size="中杯", temp="冰", quantity=3
        )

    @pytest.mark.asyncio
    async def test_colloquial_no_plus_also_merges(self):
        session = _make_session()
        reg = MagicMock()

        def _add(**kw):
            item = {
                "item_id": f"drink_{len(session['cart']) + 1}",
                "itemtype": "drink",
                "drink": "米漿" if "米漿" in kw.get("name", "") else "有糖豆漿",
                "size": "中杯",
                "temp": "溫",
                "quantity": 1,
            }
            session["cart"].append(item)
            return {"ok": True, "item_id": item["item_id"], "message": "已加入"}

        reg.add_item.side_effect = _add
        reg.add_drink.return_value = {"ok": True, "item_id": "drink_9", "message": "已加入"}
        with patch("src.services.container.tool_registry", reg):
            await execute_tags(
                "[ADD:米漿|size=中|temp=溫][ADD:豆漿|size=中|temp=溫]好～",
                "一杯中杯溫米漿豆漿",
                session,
                "s1",
            )
        reg.add_drink.assert_called_once_with(
            flavor="米漿+豆漿", size="中杯", temp="溫", quantity=1
        )

    @pytest.mark.asyncio
    async def test_separate_orders_not_merged(self):
        # 「一杯紅茶 一杯豆漿」分開點（text 無混合名）→ 不合併
        session = _make_session()
        reg = MagicMock()

        def _add(**kw):
            item = {
                "item_id": f"drink_{len(session['cart']) + 1}",
                "itemtype": "drink",
                "drink": "精選紅茶" if "紅茶" in kw.get("name", "") else "有糖豆漿",
                "quantity": 1,
            }
            session["cart"].append(item)
            return {"ok": True, "item_id": item["item_id"], "message": "已加入"}

        reg.add_item.side_effect = _add
        with patch("src.services.container.tool_registry", reg):
            await execute_tags(
                "[ADD:紅茶|size=中|temp=冰][ADD:豆漿|size=中|temp=溫]好～",
                "一杯中杯冰紅茶 一杯中杯溫豆漿",
                session,
                "s1",
            )
        reg.add_drink.assert_not_called()
        assert len(session["cart"]) == 2


class TestSwapDedup:
    """b12-07：跨品項替換兜底"""

    def _burger(self, iid, flavor):
        return {
            "item_id": iid,
            "itemtype": "carrier",
            "carrier": "漢堡",
            "flavor": flavor,
            "quantity": 1,
        }

    @pytest.mark.asyncio
    async def test_swap_removes_prev_turn_item(self):
        # 上一輪加了原味咔啦雞蛋漢堡，本輪「換成無骨雞排蛋堡」只發 ADD → 兜底移除舊的
        session = _make_session([self._burger("c1", "原味咔啦雞蛋")], last_turn_add_ids=["c1"])
        reg = MagicMock()

        def _add(**kw):
            session["cart"].append(self._burger("c2", "無骨雞排"))
            return {"ok": True, "item_id": "c2", "message": "已加入"}

        reg.add_item.side_effect = _add
        with patch("src.services.container.tool_registry", reg):
            await execute_tags("[ADD:無骨雞排蛋堡]好～", "換成無骨雞排蛋堡好了", session, "s1")
        ids = [i["item_id"] for i in session["cart"]]
        assert ids == ["c2"]

    @pytest.mark.asyncio
    async def test_customization_word_not_swap(self):
        # 「不要辣」是客製不是替換 → 不觸發跨品項刪除
        session = _make_session([self._burger("c1", "原味咔啦雞蛋")], last_turn_add_ids=["c1"])
        reg = MagicMock()

        def _add(**kw):
            session["cart"].append(self._burger("c2", "無骨雞排"))
            return {"ok": True, "item_id": "c2", "message": "已加入"}

        reg.add_item.side_effect = _add
        with patch("src.services.container.tool_registry", reg):
            await execute_tags(
                "[ADD:無骨雞排蛋堡|customization=不要辣]好～",
                "一個無骨雞排蛋堡不要辣",
                session,
                "s1",
            )
        ids = [i["item_id"] for i in session["cart"]]
        assert "c1" in ids  # 舊品項保留

    @pytest.mark.asyncio
    async def test_older_turn_item_not_swapped(self):
        # 舊品項非上一輪剛加（多人合點更早的單）→ 不誤刪
        session = _make_session([self._burger("c1", "原味咔啦雞蛋")], last_turn_add_ids=[])
        reg = MagicMock()

        def _add(**kw):
            session["cart"].append(self._burger("c2", "無骨雞排"))
            return {"ok": True, "item_id": "c2", "message": "已加入"}

        reg.add_item.side_effect = _add
        with patch("src.services.container.tool_registry", reg):
            await execute_tags("[ADD:無骨雞排蛋堡]好～", "換成無骨雞排蛋堡好了", session, "s1")
        ids = [i["item_id"] for i in session["cart"]]
        assert "c1" in ids


class TestReviewFindings31:
    """PR #31 review 修正"""

    @pytest.mark.asyncio
    async def test_pending_pay_cleared_on_pending_finalize(self):
        # 有客製待確認單：先講刷卡再答內用 → pending 單出單後 pending_pay 不殘留
        store = MagicMock()
        reg = MagicMock()
        reg.finalize_order.return_value = {"ok": True, "order_number": "01", "total": 0}
        session = {
            "checkout_status": CK_DINE,
            "cart": [
                {
                    "itemtype": "snack",
                    "snack": "港式蘿蔔糕",
                    "quantity": 1,
                    "customization": "加蛋",
                }
            ],
            "llm_history": [],
        }
        with (
            patch("src.services.container.tool_registry", reg),
            patch("src.services.container.session_store", store),
            patch("src.dm.cart_manager.cart_has_pending", return_value=True),
        ):
            _ = [e async for e in checkout_step("刷卡", "s1", session)]
            _ = [e async for e in checkout_step("內用", "s1", session)]
        reg.finalize_order.assert_called_once_with(dine_type="dine-in", payment_method="pending")
        assert "checkout_pending_pay" not in session  # 不殘留污染下一筆

    @pytest.mark.asyncio
    async def test_dine_hint_cleared_on_finalize(self):
        # hint 設了但同句 dine 直接出單沒用到 → finalize 後不殘留
        from src.api.checkout_handler import finalize_and_reply

        reg = MagicMock()
        reg.finalize_order.return_value = {"ok": True, "order_number": "02", "total": 50}
        session = {"dine_type_hint": "take-out", "checkout_status": "CHECKOUT_PAY"}
        finalize_and_reply("dine-in", "cash", session, reg)
        assert "dine_type_hint" not in session

    @pytest.mark.asyncio
    async def test_friend_wants_another_not_swapped(self):
        # 「我朋友換一個綠茶」是幫別人加點 → 不可誤刪上一輪的紅茶
        session = {
            "cart": [
                {
                    "item_id": "d1",
                    "itemtype": "drink",
                    "drink": "精選紅茶",
                    "quantity": 1,
                }
            ],
            "llm_history": [
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "raw"},
            ],
            "last_turn_add_ids": ["d1"],
        }
        reg = MagicMock()

        def _add(**kw):
            session["cart"].append(
                {"item_id": "d2", "itemtype": "drink", "drink": "無糖清香綠茶", "quantity": 1}
            )
            return {"ok": True, "item_id": "d2", "message": "已加入"}

        reg.add_item.side_effect = _add
        with patch("src.services.container.tool_registry", reg):
            await execute_tags(
                "[ADD:綠茶|size=中|temp=冰]好～", "我朋友換一個綠茶 中杯冰的", session, "s1"
            )
        ids = [i["item_id"] for i in session["cart"]]
        assert "d1" in ids  # 紅茶保留

    @pytest.mark.asyncio
    async def test_peanut_rice_milk_not_merged(self):
        # 花生糙米漿含「米漿」子字串 → 分開點不誤合併（PR #31 觀察 4）
        session = {
            "cart": [],
            "llm_history": [
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "raw"},
            ],
        }
        reg = MagicMock()

        def _add(**kw):
            item = {
                "item_id": f"d{len(session['cart']) + 1}",
                "itemtype": "drink",
                "drink": "花生糙米漿" if "糙米" in kw.get("name", "") else "有糖豆漿",
                "quantity": 1,
            }
            session["cart"].append(item)
            return {"ok": True, "item_id": item["item_id"], "message": "已加入"}

        reg.add_item.side_effect = _add
        with patch("src.services.container.tool_registry", reg):
            await execute_tags(
                "[ADD:花生糙米漿|size=中|temp=溫][ADD:豆漿|size=中|temp=溫]好～",
                "一杯花生糙米漿 一杯豆漿 都中杯溫的",
                session,
                "s1",
            )
        reg.add_drink.assert_not_called()
        assert len(session["cart"]) == 2
