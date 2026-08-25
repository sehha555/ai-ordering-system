# tests/test_leak_fixes.py
# 2026-08-25 漏單/tool-call 失效掃描後的修復回歸測試：
# 全形 tag 正規化、畸形 tag 偵測、多 REMOVE 全執行、
# 結帳同句加點不被吞、套餐去重加點閘門、結帳複述去重比對規格

import pytest
from unittest.mock import MagicMock, patch

from src.api.tag_parser import (
    ADD_RE,
    MALFORMED_TAG_RE,
    normalize_tag_text,
    strip_all_tags,
)
from src.api.text_tag_executor import execute_tags
from src.api.checkout_handler import CK_DINE, CK_PAY, checkout_step


# ── 全形 tag 正規化 ──


def test_normalize_fullwidth_colon_and_brackets():
    assert normalize_tag_text("[ADD：紅茶|size=大杯]") == "[ADD:紅茶|size=大杯]"
    assert normalize_tag_text("【ADD:紅茶】好的") == "[ADD:紅茶]好的"
    assert normalize_tag_text("[ADD:紅茶｜temp=冰]") == "[ADD:紅茶|temp=冰]"
    assert normalize_tag_text("【CHECKOUT】") == "[CHECKOUT]"


def test_normalize_halfwidth_is_identity():
    text = "[ADD:紅茶|size=大杯]好，一杯大冰紅～[CHECKOUT]"
    assert normalize_tag_text(text) == text


def test_strip_all_tags_handles_fullwidth():
    assert "ADD" not in strip_all_tags("好的【ADD:紅茶】馬上來")
    assert "SET_QTY" not in strip_all_tags("[SET_QTY：紅茶|qty=2]改兩杯")


def test_fullwidth_add_parses_after_normalize():
    assert ADD_RE.findall(normalize_tag_text("[ADD：紅茶｜temp=冰]")) == ["紅茶|temp=冰"]


# ── 畸形/截斷 tag 偵測 ──


def test_malformed_detects_truncated_tag():
    assert MALFORMED_TAG_RE.search("好的[ADD:紅茶|size=大杯")
    assert MALFORMED_TAG_RE.search("[REMOVE:紅茶[ADD:蛋餅]")


def test_malformed_ignores_wellformed():
    assert not MALFORMED_TAG_RE.search("[ADD:紅茶|size=大杯][CHECKOUT]好的")


# ── 多 REMOVE 全執行（舊版只執行第一個、其餘 strip 掉不執行）──


@pytest.mark.asyncio
async def test_multiple_remove_tags_all_executed():
    reg = MagicMock()
    reg.remove_from_cart.return_value = {"ok": True, "message": "已移除"}
    session = {
        "cart": [
            {"itemtype": "drink", "drink": "精選紅茶", "item_id": "d1", "quantity": 1},
            {"itemtype": "drink", "drink": "豆漿", "item_id": "d2", "quantity": 1},
        ],
        "llm_history": [{"role": "assistant", "content": "x"}],
    }
    with (
        patch("src.services.container.tool_registry", reg),
        patch(
            "src.api.text_tag_executor.find_cart_item_id",
            side_effect=lambda cart, kw: {"紅茶": "d1", "豆漿": "d2"}.get(kw),
        ),
    ):
        await execute_tags("[REMOVE:紅茶][REMOVE:豆漿]好的都取消～", "紅茶跟豆漿都不要了", session, "s1")
    assert reg.remove_from_cart.call_count == 2


# ── 結帳狀態機：同句夾帶具體品項 → 退出結帳給 LLM，不吞加點 ──


def _ck_session(status):
    return {
        "checkout_status": status,
        "checkout_dine_type": "take-out" if status == CK_PAY else None,
        "cart": [{"itemtype": "drink", "drink": "精選紅茶", "item_id": "d1", "quantity": 1}],
        "llm_history": [],
    }


async def _run_checkout(text, session):
    events = []
    reg = MagicMock()
    store = MagicMock()
    with (
        patch("src.services.container.tool_registry", reg),
        patch("src.services.container.session_store", store),
    ):
        async for evt in checkout_step(text, "s1", session):
            events.append(evt)
    return events, reg


@pytest.mark.asyncio
async def test_ck_pay_with_item_word_exits_instead_of_finalize():
    """「現金，順便一杯紅茶」不可直接出單 — 要退給 LLM 處理加點"""
    session = _ck_session(CK_PAY)
    events, reg = await _run_checkout("現金，順便一杯紅茶", session)
    assert events == []  # 未 yield = 退出結帳 fallthrough
    reg.finalize_order.assert_not_called()
    assert session.get("dine_type_hint") == "take-out"  # 已答的外帶不能丟


@pytest.mark.asyncio
async def test_ck_dine_with_item_word_exits():
    """「外帶，再加一個蛋餅」→ 退出結帳，外帶記進 hint"""
    session = _ck_session(CK_DINE)
    events, reg = await _run_checkout("外帶，再加一個蛋餅", session)
    assert events == []
    assert session.get("dine_type_hint") == "take-out"


@pytest.mark.asyncio
async def test_ck_dine_plain_answer_still_proceeds():
    """「我要外帶」的「我要」不可誤判成加點 — 結帳照常推進"""
    session = _ck_session(CK_DINE)
    reg_events, reg = await _run_checkout("我要外帶", session)
    assert reg_events != []  # 有 yield = 結帳有推進


# ── 套餐去重：加點意圖輪不去重 ──


def _combo_add_side_effect(session, new_id):
    def _add(**kwargs):
        session["cart"].append(
            {"itemtype": "combo", "combo_name": "套餐一", "item_id": new_id, "quantity": 1}
        )
        return {"ok": True, "item_id": new_id, "message": "已加入 套餐一"}

    return _add


@pytest.mark.asyncio
async def test_combo_dedup_skipped_on_add_more_intent():
    """「再來一份套餐一」是合法第二份，舊套餐不可被刪"""
    session = {
        "cart": [{"itemtype": "combo", "combo_name": "套餐一", "item_id": "c_old", "quantity": 1}],
        "llm_history": [{"role": "assistant", "content": "x"}],
    }
    reg = MagicMock()
    reg.add_item.side_effect = _combo_add_side_effect(session, "c_new")
    with patch("src.services.container.tool_registry", reg):
        await execute_tags("[ADD:套餐一]好的～", "再來一份套餐一", session, "s1")
    ids = {i["item_id"] for i in session["cart"]}
    assert ids == {"c_old", "c_new"}


@pytest.mark.asyncio
async def test_combo_dedup_still_works_on_modify():
    """修改語意（換溫的）重發套餐 → 舊的要被去重移除（原功能不可退化）"""
    session = {
        "cart": [{"itemtype": "combo", "combo_name": "套餐一", "item_id": "c_old", "quantity": 1}],
        "llm_history": [{"role": "assistant", "content": "x"}],
    }
    reg = MagicMock()
    reg.add_item.side_effect = _combo_add_side_effect(session, "c_new")
    with patch("src.services.container.tool_registry", reg):
        await execute_tags("[ADD:套餐一|temp=溫]換溫的～", "飲料換溫的", session, "s1")
    ids = {i["item_id"] for i in session["cart"]}
    assert ids == {"c_new"}


# ── 結帳複述去重：規格不同 = 不同品項，不可當複述刪掉 ──


@pytest.mark.asyncio
async def test_checkout_dedup_keeps_different_spec():
    """車上有中杯溫紅茶，結帳句點大杯冰紅茶 → 是第二杯，不可刪"""
    session = {
        "cart": [
            {
                "itemtype": "drink",
                "drink": "精選紅茶",
                "size": "中杯",
                "temp": "溫",
                "item_id": "d_old",
                "quantity": 1,
            }
        ],
        "llm_history": [{"role": "assistant", "content": "x"}],
    }
    reg = MagicMock()

    def _add(**kwargs):
        session["cart"].append(
            {
                "itemtype": "drink",
                "drink": "精選紅茶",
                "size": "大杯",
                "temp": "冰",
                "item_id": "d_new",
                "quantity": 1,
            }
        )
        return {"ok": True, "item_id": "d_new", "message": "已加入"}

    reg.add_item.side_effect = _add
    with patch("src.services.container.tool_registry", reg):
        await execute_tags(
            "[ADD:精選紅茶|size=大杯|temp=冰][CHECKOUT]好的～",
            "一杯大杯冰紅茶 結帳",
            session,
            "s1",
        )
    ids = {i["item_id"] for i in session["cart"]}
    assert "d_new" in ids and "d_old" in ids
