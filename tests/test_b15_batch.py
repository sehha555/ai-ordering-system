# -*- coding: utf-8 -*-
"""b15 批次修復 regression

- b15-08 單品詢價：LLM 腦補價格/謊稱沒賣/下一輪「來一個」指代迷失幻覺入車
  → pre-LLM 規則 5.5 resolver 報價 + pending_offer 橋接
"""

from tests.test_b10_batch import TestExistenceQuery as _ExistQ


class TestPriceQuery:
    """b15-08：單品詢價 pre-LLM 攔截"""

    def test_burger_price_reported(self):
        reply, llm_reached, session, _ = _ExistQ._run("一個豬肉蛋漢堡多少錢")
        assert "50元" in reply
        assert not llm_reached
        assert session["pending_offer"] == "豬肉蛋漢堡"

    def test_drink_price_both_sizes(self):
        reply, llm_reached, session, _ = _ExistQ._run("紅茶多少錢")
        assert "中杯20元" in reply and "大杯25元" in reply
        assert not llm_reached
        assert session["pending_offer"] == "精選紅茶"

    def test_offer_bridge_after_price_query(self):
        _, _, session, llm = _ExistQ._run(
            "好 來一個", session_extra={"pending_offer": "豬肉蛋漢堡"}
        )
        assert llm.run_turn_stream.call_args.kwargs["user_text"] == "我要一份豬肉蛋漢堡"

    def test_unknown_item_falls_through(self):
        _, llm_reached, _, _ = _ExistQ._run("這樣多少錢")
        assert llm_reached

    def test_multi_qty_price_query_falls_through(self):
        """「兩個蛋餅多少錢」數量詞開頭 → 不搶答（數量會被吞、口味被腦補原味）"""
        _, llm_reached, session, _ = _ExistQ._run("兩個蛋餅多少錢")
        assert llm_reached
        assert "pending_offer" not in session

    def test_single_qty_prefix_still_intercepted(self):
        """「一個豬肉蛋漢堡多少錢」前綴「一個」被 regex 消化 → 照攔"""
        reply, llm_reached, _, _ = _ExistQ._run("一份豬肉蛋漢堡多少錢")
        assert "50元" in reply
        assert not llm_reached

    def test_order_sentence_not_intercepted(self):
        _, llm_reached, _, _ = _ExistQ._run("我要一個豬肉蛋漢堡")
        assert llm_reached


class TestQtyRecover:
    """b15-07：tag 漏 qty 但 text 明說數量 → 補回"""

    @staticmethod
    async def _exec(tag_text, user_text):
        from unittest.mock import MagicMock, patch

        from src.api.text_tag_executor import execute_tags

        reg = MagicMock()
        reg.add_item.return_value = {"ok": True, "item_id": "x1", "message": "已加入"}
        session = {"cart": [], "llm_history": []}
        with patch("src.services.container.tool_registry", reg):
            await execute_tags(tag_text, user_text, session, "s1")
        return reg

    import pytest as _pytest

    @_pytest.mark.asyncio
    async def test_missing_qty_recovered_from_text(self):
        """「兩個紫米甜飯糰」tag 漏 qty → 補 quantity=2（修飾詞隔開也可）"""
        reg = await self._exec(
            "[ADD:甜飯糰|rice=紫米]好～",
            "三個火腿蛋饅頭 兩個紫米甜飯糰",
        )
        assert reg.add_item.call_args.kwargs["quantity"] == 2

    @_pytest.mark.asyncio
    async def test_explicit_qty_not_overridden(self):
        """tag 已帶 qty=2 → 不動"""
        reg = await self._exec(
            "[ADD:甜飯糰|rice=紫米|qty=2]好～",
            "兩個紫米甜飯糰",
        )
        assert reg.add_item.call_args.kwargs["quantity"] == 2

    @_pytest.mark.asyncio
    async def test_qty_one_in_text_not_added(self):
        """「一個」N=1 不補（維持缺省）"""
        reg = await self._exec(
            "[ADD:玉米蛋餅]好～",
            "一個玉米蛋餅",
        )
        assert "quantity" not in reg.add_item.call_args.kwargs

    @_pytest.mark.asyncio
    async def test_item_not_in_text_not_recovered(self):
        """品項名不在 text（俗稱輪）→ 不觸發"""
        reg = await self._exec(
            "[ADD:純鮮奶茶|size=大杯|temp=冰]好～",
            "兩杯大冰奶",
        )
        assert "quantity" not in reg.add_item.call_args.kwargs
