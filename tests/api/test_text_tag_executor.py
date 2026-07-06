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


def _session_with_item():
    """含一項點心的 session（非空車場景共用）"""
    return _make_session([{"itemtype": "snack", "snack": "薯餅(1片)", "quantity": 1}])


@pytest.fixture
def registry():
    """mock tool_registry：add_item 成功、finalize_order 成功出 01 號單"""
    reg = MagicMock()
    reg.add_item.return_value = {"ok": True, "item_id": "i1", "message": "已加入豆漿"}
    reg.finalize_order.return_value = {"ok": True, "order_number": "01", "total": 90}
    with patch("src.services.container.tool_registry", reg):
        yield reg


@pytest.mark.asyncio
async def test_checkout_with_dine_and_payment_finalizes(registry):
    """同句帶外帶+現金 → 直接 finalize，回覆帶單號"""
    session = _session_with_item()

    result = await execute_tags("[CHECKOUT]好～", "結帳 外帶 現金", session, "s1")

    registry.finalize_order.assert_called_once_with(dine_type="take-out", payment_method="cash")
    assert result.finalize_result["order_number"] == "01"
    assert "01號" in result.full_text
    assert "checkout_status" not in session


@pytest.mark.asyncio
async def test_checkout_with_dine_only_advances_to_pay(registry):
    """同句只帶外帶 → 進 CK_PAY 問付款方式"""
    session = _session_with_item()

    result = await execute_tags("[CHECKOUT]好～", "結帳 外帶", session, "s1")

    registry.finalize_order.assert_not_called()
    assert session["checkout_status"] == CK_PAY
    assert session["checkout_dine_type"] == "take-out"
    assert "現金" in result.full_text
    assert result.finalize_result is None


@pytest.mark.asyncio
async def test_checkout_without_dine_stays_in_dine_state(registry):
    """同句沒帶內用外帶 → 維持 CK_DINE（既有行為，下輪狀態機接手）"""
    session = _session_with_item()

    result = await execute_tags("[CHECKOUT]內用還是外帶？", "結帳", session, "s1")

    registry.finalize_order.assert_not_called()
    assert session["checkout_status"] == CK_DINE
    assert result.finalize_result is None
    # 第一問由後端組確認句（複述品項+總金額），取代 LLM 話術
    assert "跟您確認" in result.full_text
    assert "內用還是外帶" in result.full_text
    assert session["llm_history"][-1]["content"] == result.full_text


@pytest.mark.asyncio
async def test_compound_add_and_checkout_adds_before_finalize(registry):
    """複合句 [ADD][CHECKOUT] → 先 add_item 再 finalize（品項不漏單）"""
    session = _session_with_item()

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
    session = _session_with_item()

    result = await execute_tags(
        "[ADD:鮪魚飯糰][CHECKOUT]好～",
        "一個鮪魚飯糰 結帳 外帶 現金",
        session,
        "s1",
    )

    registry.finalize_order.assert_not_called()
    # 結帳狀態必須撤回：否則下輪補槽回答（如「紫米」）會被結帳狀態機吃掉
    assert "checkout_status" not in session
    assert result.finalize_result is None


@pytest.mark.asyncio
async def test_empty_cart_add_success_checkout_finalizes(registry):
    """空車起單：ADD 成功入車 + 同句外帶現金 → 一次到位 finalize"""
    session = _make_session(cart=[])

    def _add_item(**kwargs):
        session["cart"].append({"itemtype": "drink", "flavor": kwargs["name"], "quantity": 1})
        return {"ok": True, "item_id": "i1", "message": "已加入豆漿"}

    registry.add_item.side_effect = _add_item

    result = await execute_tags(
        "[ADD:豆漿|size=大杯|temp=冰][CHECKOUT]好～",
        "一杯大杯冰豆漿 結帳 外帶 現金",
        session,
        "s1",
    )

    registry.finalize_order.assert_called_once_with(dine_type="take-out", payment_method="cash")
    assert result.finalize_result is not None
    assert "01號" in result.full_text


@pytest.mark.asyncio
async def test_empty_cart_add_failed_checkout_retracted(registry):
    """空車放行進結帳但 ADD 未入車（品項不存在）→ 結帳狀態撤回"""
    registry.add_item.return_value = {"ok": False, "message": "我們沒有賣珍珠奶茶喔"}
    session = _make_session(cart=[])

    result = await execute_tags(
        "[ADD:珍珠奶茶][CHECKOUT]好～",
        "一杯珍珠奶茶 結帳 外帶 現金",
        session,
        "s1",
    )

    registry.finalize_order.assert_not_called()
    assert "checkout_status" not in session
    assert result.finalize_result is None


@pytest.mark.asyncio
async def test_add_failed_with_prose_sets_followup(registry):
    """LLM prose 非空 + ADD 失敗 → followup_text 仍須設定（否則追問被吞客人死等）"""
    registry.add_item.return_value = {"ok": False, "message": "冰的還是溫的？"}
    session = _make_session(cart=[])

    result = await execute_tags(
        "[ADD:米漿+豆漿|size=中杯]好～還要什麼？", "再一杯米漿", session, "s1"
    )

    assert result.followup_text == "冰的還是溫的？"
    assert "冰的還是溫的" in result.full_text


@pytest.mark.asyncio
async def test_modify_intent_dedups_same_item(registry):
    """修改語意（不要辣）誤發新 ADD → 同款舊品項移除，不變兩份"""
    old_item = {
        "item_id": "riceball_1",
        "itemtype": "riceball",
        "flavor": "鮪魚飯糰",
        "rice": "紫米",
        "quantity": 1,
    }
    session = _make_session(cart=[old_item])
    session["last_turn_add_ids"] = ["riceball_1"]  # 上一輪剛加的（修改窗口內）

    def _add_item(**kwargs):
        new_item = {
            "item_id": "riceball_2",
            "itemtype": "riceball",
            "flavor": "鮪魚飯糰",
            "rice": "紫米",
            "customization": "不要辣菜脯",
            "quantity": 1,
        }
        session["cart"].append(new_item)
        return {"ok": True, "item_id": "riceball_2", "message": "已加入"}

    registry.add_item.side_effect = _add_item

    await execute_tags(
        "[ADD:鮪魚飯糰|rice=紫米|customization=不要辣菜脯]好～", "不要辣 這樣就好", session, "s1"
    )

    cart = session["cart"]
    assert len(cart) == 1, f"同款品項應去重為 1 個，實際 {len(cart)} 個"
    assert cart[0]["item_id"] == "riceball_2"


@pytest.mark.asyncio
async def test_modify_intent_spares_earlier_turn_items(registry):
    """多人合點：更早輪的同款品項不在上一輪 ADD 窗口 → 修改語意不誤刪"""
    old_item = {
        "item_id": "riceball_1",
        "itemtype": "riceball",
        "flavor": "鮪魚飯糰",
        "rice": "白米",
        "quantity": 1,
    }
    session = _make_session(cart=[old_item])
    session["last_turn_add_ids"] = ["drink_9"]  # 上一輪加的是別的品項

    def _add_item(**kwargs):
        new_item = {
            "item_id": "riceball_2",
            "itemtype": "riceball",
            "flavor": "鮪魚飯糰",
            "rice": "紫米",
            "customization": "不要辣菜脯",
            "quantity": 1,
        }
        session["cart"].append(new_item)
        return {"ok": True, "item_id": "riceball_2", "message": "已加入"}

    registry.add_item.side_effect = _add_item

    await execute_tags(
        "[ADD:鮪魚飯糰|rice=紫米|customization=不要辣菜脯]好～",
        "我要一份鮪魚飯糰不要辣",
        session,
        "s1",
    )

    assert len(session["cart"]) == 2, "更早輪的同款品項（別人的訂單）不應被誤刪"


@pytest.mark.asyncio
async def test_add_more_intent_keeps_both_items(registry):
    """加點語意（再一個）→ 不去重，兩份都保留"""
    old_item = {
        "item_id": "riceball_1",
        "itemtype": "riceball",
        "flavor": "鮪魚飯糰",
        "rice": "紫米",
        "quantity": 1,
    }
    session = _make_session(cart=[old_item])

    def _add_item(**kwargs):
        new_item = {
            "item_id": "riceball_2",
            "itemtype": "riceball",
            "flavor": "鮪魚飯糰",
            "rice": "白米",
            "quantity": 1,
        }
        session["cart"].append(new_item)
        return {"ok": True, "item_id": "riceball_2", "message": "已加入"}

    registry.add_item.side_effect = _add_item

    await execute_tags("[ADD:鮪魚飯糰|rice=白米]好～", "再一個鮪魚飯糰 白米的", session, "s1")

    assert len(session["cart"]) == 2, "加點語意不應去重"


@pytest.mark.asyncio
async def test_slot_fill_retry_not_treated_as_modify(registry):
    """補槽回答含修改詞（換紫米的）→ retry 品項不參與修改去重，既有同款不被誤刪"""
    old_item = {
        "item_id": "riceball_1",
        "itemtype": "riceball",
        "flavor": "鮪魚飯糰",
        "rice": "白米",
        "quantity": 1,
    }
    session = _make_session(cart=[old_item])
    session["last_turn_add_ids"] = ["riceball_1"]  # 即使在修改窗口內，retry 品項也不觸發
    session["last_failed_attempt"] = {
        "item_name": "鮪魚飯糰",
        "missing": ["rice"],
        "provided": {},
    }

    def _add_item(**kwargs):
        if kwargs["name"] == "鮪魚飯糰":  # 補槽 retry
            new_item = {
                "item_id": "riceball_2",
                "itemtype": "riceball",
                "flavor": "鮪魚飯糰",
                "rice": "紫米",
                "quantity": 1,
            }
            session["cart"].append(new_item)
            return {"ok": True, "item_id": "riceball_2", "message": "已加入"}
        return {"ok": False, "message": "沒有這個品項"}  # LLM 把答案當品項

    registry.add_item.side_effect = _add_item

    await execute_tags("[ADD:紫米飯糰|rice=紫米]好～", "換紫米的", session, "s1")

    assert len(session["cart"]) == 2, "補槽 retry 不應觸發修改去重誤刪既有品項"


@pytest.mark.asyncio
async def test_affirmative_answer_dedups_without_modify_words(registry):
    """追問肯定回答（要辣）text 沒點名品項 → 視為修改去重，不變兩份"""
    old_item = {
        "item_id": "riceball_1",
        "itemtype": "riceball",
        "flavor": "鮪魚飯糰",
        "rice": "紫米",
        "quantity": 1,
    }
    session = _make_session(cart=[old_item])
    session["last_turn_add_ids"] = ["riceball_1"]

    def _add_item(**kwargs):
        new_item = {
            "item_id": "riceball_2",
            "itemtype": "riceball",
            "flavor": "鮪魚飯糰",
            "rice": "紫米",
            "spicy": True,
            "quantity": 1,
        }
        session["cart"].append(new_item)
        return {"ok": True, "item_id": "riceball_2", "message": "已加入"}

    registry.add_item.side_effect = _add_item

    await execute_tags("[ADD:鮪魚飯糰|rice=紫米|spicy=true]好～", "要辣 謝謝", session, "s1")

    cart = session["cart"]
    assert len(cart) == 1, f"肯定回答應去重為 1 個，實際 {len(cart)} 個"
    assert cart[0]["item_id"] == "riceball_2"


@pytest.mark.asyncio
async def test_named_item_not_deduped_without_modify_words(registry):
    """text 點名品項（第二人接著點同款）→ 無修改詞不去重"""
    old_item = {
        "item_id": "riceball_1",
        "itemtype": "riceball",
        "flavor": "鮪魚飯糰",
        "rice": "紫米",
        "quantity": 1,
    }
    session = _make_session(cart=[old_item])
    session["last_turn_add_ids"] = ["riceball_1"]

    def _add_item(**kwargs):
        session["cart"].append(
            {
                "item_id": "riceball_2",
                "itemtype": "riceball",
                "flavor": "鮪魚飯糰",
                "rice": "白米",
                "quantity": 1,
            }
        )
        return {"ok": True, "item_id": "riceball_2", "message": "已加入"}

    registry.add_item.side_effect = _add_item

    await execute_tags("[ADD:鮪魚飯糰|rice=白米]好～", "一個鮪魚飯糰白米", session, "s1")

    assert len(session["cart"]) == 2, "點名品項的新單不應被去重"


@pytest.mark.asyncio
async def test_checkout_restate_dedups_new_item(registry):
    """結帳輪複述已在車上的品項 → 移除新的重複 ADD"""
    old_item = {"item_id": "snack_1", "itemtype": "snack", "snack": "港式蘿蔔糕", "quantity": 1}
    session = _make_session(cart=[old_item])
    session["last_turn_add_ids"] = []  # 蘿蔔糕是更早輪點的

    def _add_item(**kwargs):
        session["cart"].append(
            {"item_id": "snack_2", "itemtype": "snack", "snack": "港式蘿蔔糕", "quantity": 1}
        )
        return {"ok": True, "item_id": "snack_2", "message": "已加入"}

    registry.add_item.side_effect = _add_item

    await execute_tags("[ADD:港式蘿蔔糕][CHECKOUT]好～", "蘿蔔糕一份 就這些 結帳", session, "s1")

    cart = session["cart"]
    assert len(cart) == 1, f"結帳複述應去重為 1 個，實際 {len(cart)} 個"
    assert cart[0]["item_id"] == "snack_1", "應保留舊品項移除複述的新 ADD"


@pytest.mark.asyncio
async def test_hallucinated_slot_stripped(registry):
    """text 沒提米種但 ADD 帶 rice → strip 讓 missing 機制追問（不擅自入車）"""
    session = _make_session(cart=[])
    registry.add_item.return_value = {"ok": False, "missing": ["rice"], "message": "要紫米白米？"}

    await execute_tags("[ADD:鮪魚飯糰|rice=白米]好～", "鮪魚飯糰一個", session, "s1")

    registry.add_item.assert_called_once()
    assert "rice" not in registry.add_item.call_args.kwargs, "腦補的 rice 應被 strip"


@pytest.mark.asyncio
async def test_text_backed_slot_kept(registry):
    """text 有講「紫」→ rice 保留正常入車"""
    session = _make_session(cart=[])

    await execute_tags("[ADD:鮪魚飯糰|rice=紫米]好～", "一個鮪魚飯糰紫米", session, "s1")

    assert registry.add_item.call_args.kwargs.get("rice") == "紫米"


@pytest.mark.asyncio
async def test_modify_turn_slot_exempt(registry):
    """修改輪（不要辣）屬性來自 context 記憶 → 不 strip"""
    session = _make_session(cart=list(_make_session()["cart"]))

    await execute_tags("[ADD:鮪魚飯糰|rice=紫米|spicy=false]好～", "不要辣 這樣就好", session, "s1")

    assert registry.add_item.call_args.kwargs.get("rice") == "紫米", "修改輪不應 strip context 屬性"


@pytest.mark.asyncio
async def test_context_turn_slot_exempt(registry):
    """context 輪（要辣，沒點名品項）→ 不 strip"""
    session = _make_session(cart=[])

    await execute_tags("[ADD:鮪魚飯糰|rice=紫米|spicy=true]好～", "要辣 謝謝", session, "s1")

    assert registry.add_item.call_args.kwargs.get("rice") == "紫米", "context 輪不應 strip"


@pytest.mark.asyncio
async def test_add_one_more_qty_corrected(registry):
    """「再加一份」LLM 誤發 qty=2 → 後端修正為 +1"""
    old_item = {
        "item_id": "ep_1",
        "itemtype": "egg_pancake",
        "flavor": "原味蛋餅",
        "quantity": 1,
    }
    session = _make_session(cart=[old_item])
    session["last_turn_add_ids"] = ["ep_1"]

    def _add_item(**kwargs):
        new_item = {
            "item_id": "ep_2",
            "itemtype": "egg_pancake",
            "flavor": "原味蛋餅",
            "quantity": kwargs.get("quantity", 1),
        }
        session["cart"].append(new_item)
        return {"ok": True, "item_id": "ep_2", "message": "已加入"}

    registry.add_item.side_effect = _add_item

    await execute_tags("[ADD:原味蛋餅|qty=2]好～", "蛋餅再加一份", session, "s1")

    new_item = next(i for i in session["cart"] if i["item_id"] == "ep_2")
    assert new_item["quantity"] == 1, "「再加一份」qty 應被修正為 1"
    total_qty = sum(i["quantity"] for i in session["cart"])
    assert total_qty == 2, f"總量應為 2（原 1 + 新 1），實際 {total_qty}"


@pytest.mark.asyncio
async def test_add_two_more_qty_untouched(registry):
    """「再加兩份」qty=2 是正確增量 → 不修正"""
    session = _make_session(
        cart=[{"item_id": "ep_1", "itemtype": "egg_pancake", "flavor": "原味蛋餅", "quantity": 1}]
    )

    def _add_item(**kwargs):
        session["cart"].append(
            {
                "item_id": "ep_2",
                "itemtype": "egg_pancake",
                "flavor": "原味蛋餅",
                "quantity": kwargs.get("quantity", 1),
            }
        )
        return {"ok": True, "item_id": "ep_2", "message": "已加入"}

    registry.add_item.side_effect = _add_item

    await execute_tags("[ADD:原味蛋餅|qty=2]好～", "蛋餅再加兩份", session, "s1")

    new_item = next(i for i in session["cart"] if i["item_id"] == "ep_2")
    assert new_item["quantity"] == 2, "「再加兩份」不應被修正"


@pytest.mark.asyncio
async def test_checkout_fallback_without_tag(registry):
    """LLM 漏發 [CHECKOUT] 但客人明說結帳 → 後端兜底推進 finalize，話術經 followup 補送"""
    session = _session_with_item()

    result = await execute_tags("好～外帶付現金喔！", "結帳 外帶 現金", session, "s1")

    registry.finalize_order.assert_called_once_with(dine_type="take-out", payment_method="cash")
    assert result.finalize_result is not None
    assert "01號" in result.followup_text, "兜底輪話術需經 followup 補送（prose 已 streaming）"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "user_text",
    ["先不要結帳 我再想想", "不要結帳", "等一下結帳", "還沒要結帳", "晚點再結帳"],
)
async def test_checkout_fallback_negated_not_triggered(registry, user_text):
    """延後/否定語意 → 兜底不觸發，不進結帳狀態機"""
    session = _session_with_item()

    result = await execute_tags("好的～", user_text, session, "s1")

    registry.finalize_order.assert_not_called()
    assert "checkout_status" not in session
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


# ── E 族：套餐追問鏈中結帳（pending_checkout 接續機制）──


def _pending_attempt():
    return {
        "item_name": "套餐C",
        "missing": ["temp"],
        "provided": {},
        "message": "飲料要冰的還是溫的？",
    }


def _cart_appending_add(session, item_id):
    """add_item side_effect：把品項塞進 session cart 並回成功"""

    def _add(**kwargs):
        session["cart"].append(
            {"itemtype": "snack", "snack": kwargs["name"], "quantity": 1, "item_id": item_id}
        )
        return {"ok": True, "item_id": item_id, "message": f"已加入{kwargs['name']}"}

    return _add


@pytest.mark.asyncio
async def test_checkout_during_slot_chain_replays_question(registry):
    """空車 + pending 追問 + [CHECKOUT] → 重放追問而非「空的」，記 pending flag"""
    session = _make_session(cart=[])
    session["last_failed_attempt"] = _pending_attempt()

    result = await execute_tags("[CHECKOUT]好～", "好了 幫我結帳", session, "s1")

    assert "空的" not in result.full_text
    assert "飲料要冰的還是溫的" in result.full_text
    assert session["pending_checkout"] is True
    assert "checkout_status" not in session
    assert session["llm_history"][-1]["content"] == result.full_text


@pytest.mark.asyncio
async def test_checkout_during_slot_chain_without_tag(registry):
    """同場景但 LLM 沒發 tag（prose 自答空車）→ 追問經 followup 補送，記 flag"""
    session = _make_session(cart=[])
    session["last_failed_attempt"] = _pending_attempt()

    result = await execute_tags("購物車還是空的喔，要點什麼？", "好了 幫我結帳", session, "s1")

    assert "飲料要冰的還是溫的" in result.followup_text
    assert session["pending_checkout"] is True
    assert "checkout_status" not in session


@pytest.mark.asyncio
async def test_pending_checkout_resumes_after_slot_filled(registry):
    """pending flag + 本輪補槽成功 → 自動接回結帳，出確認句（經 followup 補送）"""
    session = _make_session(cart=[])
    session["last_failed_attempt"] = _pending_attempt()
    session["pending_checkout"] = True

    registry.add_item.side_effect = _cart_appending_add(session, "c1")

    result = await execute_tags("[ADD:套餐C|temp=冰]好～", "冰的", session, "s1")

    assert session["checkout_status"] == CK_DINE
    assert "跟您確認" in result.full_text
    assert "跟您確認" in result.followup_text, "本輪 prose 已 streaming，確認句需經 followup 補送"
    assert session["last_failed_attempt"] is None
    assert "pending_checkout" not in session


@pytest.mark.asyncio
async def test_pending_checkout_dropped_on_add_more(registry):
    """pending flag 輪客人改口加點 → 放掉結帳意圖，回一般點餐流程"""
    session = _make_session(cart=[])
    session["last_failed_attempt"] = _pending_attempt()
    session["pending_checkout"] = True

    registry.add_item.side_effect = _cart_appending_add(session, "s9")

    result = await execute_tags("[ADD:薯餅(1片)]好～", "等等 我還要一份薯餅", session, "s1")

    assert "checkout_status" not in session
    assert "pending_checkout" not in session
    assert result.finalize_result is None


@pytest.mark.asyncio
async def test_pending_checkout_dropped_on_negate_with_slot_answer(registry):
    """補槽同句否定結帳（「先不要結帳 熱的好了」）→ 不搶跑進結帳，flag 丟棄"""
    session = _make_session(cart=[])
    session["last_failed_attempt"] = _pending_attempt()
    session["pending_checkout"] = True

    registry.add_item.side_effect = _cart_appending_add(session, "c1")

    result = await execute_tags(
        "[ADD:套餐C|temp=熱]好～", "先不要結帳 那溫度就熱的好了", session, "s1"
    )

    assert "checkout_status" not in session
    assert "pending_checkout" not in session
    assert result.finalize_result is None
    assert "跟您確認" not in result.full_text


@pytest.mark.asyncio
async def test_pending_checkout_persists_while_slot_still_missing(registry):
    """pending flag 輪補槽又失敗 → flag 延續到下一輪"""
    registry.add_item.return_value = {
        "ok": False,
        "missing": ["temp"],
        "message": "飲料要冰的還是溫的？",
    }
    session = _make_session(cart=[])
    session["last_failed_attempt"] = _pending_attempt()
    session["pending_checkout"] = True

    await execute_tags("[ADD:套餐C]好～", "三號餐", session, "s1")

    assert session["pending_checkout"] is True
    assert "checkout_status" not in session


@pytest.mark.asyncio
async def test_checkout_retracted_on_slot_missing_sets_pending(registry):
    """同句點餐+結帳但 ADD 缺槽撤回結帳 → 記 pending flag 供補槽後接回"""
    registry.add_item.return_value = {
        "ok": False,
        "missing": ["temp"],
        "message": "飲料要冰的還是溫的？",
    }
    session = _make_session(cart=[])

    result = await execute_tags("[ADD:套餐C][CHECKOUT]好～", "一個三號餐 結帳", session, "s1")

    assert "checkout_status" not in session
    assert session["pending_checkout"] is True
    assert "飲料要冰的還是溫的" in result.full_text


@pytest.mark.asyncio
async def test_checkout_with_cart_and_pending_slot_replays_question(registry):
    """車上有品項但另一品項還在補槽 → 結帳撤回 + 重放追問（非空車路徑同樣接住）"""
    session = _session_with_item()
    session["last_failed_attempt"] = _pending_attempt()

    result = await execute_tags("[CHECKOUT]內用還是外帶？", "結帳", session, "s1")

    assert "checkout_status" not in session
    assert session["pending_checkout"] is True
    assert "飲料要冰的還是溫的" in result.full_text
    assert "飲料要冰的還是溫的" in result.followup_text


@pytest.mark.asyncio
async def test_empty_cart_checkout_no_pending_still_rejected(registry):
    """空車純結帳且無 pending 追問 → 仍回「購物車是空的」（既有行為不變）"""
    session = _make_session(cart=[])

    result = await execute_tags("[CHECKOUT]好～", "結帳", session, "s1")

    assert "空的" in result.full_text
    assert "pending_checkout" not in session


# ── V9：LLM prose 已追問缺槽 → 後端 followup 不疊問 ──


def _missing_temp_add(registry):
    registry.add_item.return_value = {
        "ok": False,
        "missing": ["temp"],
        "message": "飲料冰的還是溫的",
    }


@pytest.mark.asyncio
async def test_followup_suppressed_when_prose_asks_same_slot(registry):
    """prose 已問「冰的還是溫的？」→ 同缺槽 followup 不疊問"""
    _missing_temp_add(registry)
    session = _make_session(cart=[])

    result = await execute_tags("[ADD:套餐C]飲料要冰的還是溫的？", "一個三號餐", session, "s1")

    assert result.followup_text == ""
    assert result.full_text == "飲料要冰的還是溫的？"


@pytest.mark.asyncio
async def test_followup_sent_when_prose_silent_on_slot(registry):
    """prose 沒問缺槽 → followup 照補（既有行為不變）"""
    _missing_temp_add(registry)
    session = _make_session(cart=[])

    result = await execute_tags("[ADD:套餐C]好的～", "一個三號餐", session, "s1")

    assert "冰的還是溫的" in result.followup_text


@pytest.mark.asyncio
async def test_followup_sent_when_prose_covers_only_partial_slots(registry):
    """缺兩槽 prose 只問一槽 → followup 照補（寧可重複不可漏問）"""
    registry.add_item.return_value = {
        "ok": False,
        "missing": ["temp", "rice"],
        "message": "要紫米白米？飲料冰的還是溫的",
    }
    session = _make_session(cart=[])

    result = await execute_tags("[ADD:套餐C]飲料要冰的還是溫的？", "一個三號餐", session, "s1")

    assert "紫米白米" in result.followup_text


@pytest.mark.asyncio
async def test_followup_sent_for_unmapped_slot(registry):
    """缺槽不在 marker 表（noodle）→ 無法確認 prose 已問，照補"""
    registry.add_item.return_value = {
        "ok": False,
        "missing": ["noodle"],
        "message": "油麵還是烏龍麵",
    }
    session = _make_session(cart=[])

    result = await execute_tags("[ADD:蘑菇鐵板麵]油麵還是烏龍麵？", "一個蘑菇鐵板麵", session, "s1")

    assert "油麵還是烏龍麵" in result.followup_text


@pytest.mark.asyncio
async def test_followup_sent_when_prose_has_no_question_mark(registry):
    """prose 含選項詞但無問號（非追問語氣）→ followup 照補"""
    _missing_temp_add(registry)
    session = _make_session(cart=[])

    result = await execute_tags("[ADD:套餐C]我們有冰的和溫的喔", "一個三號餐", session, "s1")

    assert "冰的還是溫的" in result.followup_text


@pytest.mark.asyncio
async def test_followup_sent_when_multiple_items_share_missing_slot(registry):
    """兩品項同缺 temp、prose 只問一杯 → 全部照補（不誤吞第二杯的追問）"""
    registry.add_item.side_effect = [
        {"ok": False, "missing": ["temp"], "message": "紅茶冰的還是溫的"},
        {"ok": False, "missing": ["temp"], "message": "奶茶冰的還是溫的"},
    ]
    session = _make_session(cart=[])

    result = await execute_tags(
        "[ADD:精選紅茶][ADD:純鮮奶茶]紅茶要冰的還是溫的？", "一杯紅茶一杯奶茶", session, "s1"
    )

    assert "奶茶冰的還是溫的" in result.followup_text


@pytest.mark.asyncio
async def test_followup_sent_on_common_char_false_positive(registry):
    """prose 含常用字 大+中+問號 但非追問尺寸 → followup 照補"""
    registry.add_item.return_value = {
        "ok": False,
        "missing": ["size"],
        "message": "要中杯還是大杯",
    }
    session = _make_session(cart=[])

    result = await execute_tags(
        "[ADD:精選紅茶]好的，這道大概中午前都有現做，還需要什麼呢？", "一杯紅茶", session, "s1"
    )

    assert "中杯還是大杯" in result.followup_text
