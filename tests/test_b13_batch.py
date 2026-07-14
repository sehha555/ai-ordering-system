# tests/test_b13_batch.py
# b13-08 補槽輪套餐組成具體化幻覺：
# 套餐五追問「饅頭要什麼口味」客人答「起司的 溫的」，LLM 不重發套餐名，
# 發 [ADD:起司蛋饅頭|flavor=起司|temp=溫]（或全名後綴「起司蛋饅頭+燕麥薏仁漿」）
# → fuzzy 解成單品饅頭入車（$45 vs $75），attempt 懸置引發空車謊言整單蒸發

import pytest
from unittest.mock import MagicMock, patch

from src.api.text_tag_executor import execute_tags


def _combo5_retry_session():
    """套餐五補槽中：缺 temp/flavor（混單場景，車上已有鐵板麵）"""
    return {
        "cart": [
            {
                "itemtype": "snack",
                "snack": "蘑菇鐵板麵(烏龍)+蛋",
                "quantity": 1,
                "item_id": "snack_1",
            }
        ],
        "llm_history": [
            {"role": "user", "content": "一個蘑菇鐵板麵烏龍麵 加一份套餐五"},
            {"role": "assistant", "content": "饅頭要什麼口味？飲料冰的還是溫的？"},
        ],
        "last_failed_attempt": {
            "item_name": "套餐五",
            "missing": ["temp", "flavor"],
            "provided": {},
            "message": "飲料冰的還是溫的 饅頭要什麼口味",
        },
    }


@pytest.mark.asyncio
async def test_materialized_component_renamed_to_combo():
    """補槽輪 [ADD:起司蛋饅頭|flavor=起司|temp=溫] → 換回套餐五，參數保留"""
    reg = MagicMock()
    reg.add_item.return_value = {"ok": True, "item_id": "combo_1", "message": "已加入"}
    session = _combo5_retry_session()
    with patch("src.services.container.tool_registry", reg):
        await execute_tags(
            "[ADD:起司蛋饅頭|flavor=起司|temp=溫]好～還要什麼？",
            "起司的 溫的",
            session,
            "s1",
        )
    reg.add_item.assert_called_once_with(name="套餐五", flavor="起司", temp="溫")


@pytest.mark.asyncio
async def test_materialized_fullname_suffix_renamed():
    """LLM 發 menu 全名後綴「起司蛋饅頭+燕麥薏仁漿」→ 同樣換回套餐五"""
    reg = MagicMock()
    reg.add_item.return_value = {"ok": True, "item_id": "combo_1", "message": "已加入"}
    session = _combo5_retry_session()
    with patch("src.services.container.tool_registry", reg):
        await execute_tags(
            "[ADD:起司蛋饅頭+燕麥薏仁漿|temp=溫|flavor=起司]好～還要什麼？",
            "起司的 溫的",
            session,
            "s1",
        )
    reg.add_item.assert_called_once_with(name="套餐五", flavor="起司", temp="溫")


@pytest.mark.asyncio
async def test_explicit_component_order_not_renamed():
    """客人完整點名「一個起司蛋饅頭」→ 真的想點單品，不換名"""
    reg = MagicMock()
    reg.add_item.return_value = {"ok": True, "item_id": "carrier_1", "message": "已加入"}
    session = _combo5_retry_session()
    with patch("src.services.container.tool_registry", reg):
        await execute_tags(
            "[ADD:起司蛋饅頭]好～還要什麼？",
            "先來一個起司蛋饅頭",
            session,
            "s1",
        )
    assert reg.add_item.call_args.kwargs["name"] == "起司蛋饅頭"


@pytest.mark.asyncio
async def test_no_attempt_not_renamed():
    """無 attempt（非補槽輪）→ 不換名"""
    reg = MagicMock()
    reg.add_item.return_value = {"ok": True, "item_id": "carrier_1", "message": "已加入"}
    session = {"cart": [], "llm_history": []}
    with patch("src.services.container.tool_registry", reg):
        await execute_tags(
            "[ADD:起司蛋饅頭|flavor=起司]好～還要什麼？",
            "一個起司的饅頭",
            session,
            "s1",
        )
    assert reg.add_item.call_args.kwargs["name"] == "起司蛋饅頭"


# b9-05 猶豫客重複入車：換品項輪 LLM 已入車半甜鹹(紫米)，客人冗餘補「一樣紫米」
# LLM 重發同款 ADD → modify-dedup 該攔，卻因顯示名「紫米·半甜鹹」的米種前綴
# 命中 text「紫米」被誤判為點名品項而放行 → x2 出錯單


def test_rice_attr_piece_not_item_mention():
    from src.api.tag_parser import item_mentioned_in_text

    riceball = {"itemtype": "riceball", "flavor": "半甜鹹", "rice": "紫米", "quantity": 1}
    assert not item_mentioned_in_text(riceball, "一樣紫米")
    assert item_mentioned_in_text(riceball, "半甜鹹的不要好了")


@pytest.mark.asyncio
async def test_redundant_rice_answer_dedups_duplicate_add():
    """「一樣紫米」輪 LLM 重發同款 ADD → modify-dedup 移除舊品項，車上只留一份"""
    from src.dm.dialogue_manager import DialogueManager
    from src.dm.session_store import InMemorySessionStore
    from src.dm.tool_registry import ToolRegistry

    store = InMemorySessionStore()
    dm = DialogueManager(llm=None, store=store)
    tr = ToolRegistry(dm, store)
    sid = "b9-05-test"
    tr.set_session_id(sid)
    first = tr.add_item(name="半甜鹹飯糰", rice="紫米")
    session = store.get(sid)
    session["last_turn_add_ids"] = [first["item_id"]]
    session["llm_history"] = [
        {"role": "user", "content": "等等 甜飯糰不要好了 換半甜鹹飯糰"},
        {"role": "assistant", "content": "好，要加辣菜脯嗎？"},
    ]
    with patch("src.services.container.tool_registry", tr):
        await execute_tags(
            "[ADD:半甜鹹飯糰|rice=紫米]好～還要什麼？",
            "一樣紫米",
            session,
            sid,
        )
    riceballs = [i for i in session["cart"] if i.get("itemtype") == "riceball"]
    assert len(riceballs) == 1


@pytest.mark.asyncio
async def test_unrelated_item_not_renamed():
    """補槽輪加點與套餐組成無關的品項 → 不換名"""
    reg = MagicMock()
    reg.add_item.return_value = {"ok": True, "item_id": "ep_1", "message": "已加入"}
    session = _combo5_retry_session()
    with patch("src.services.container.tool_registry", reg):
        await execute_tags(
            "[ADD:玉米蛋餅]好～還要什麼？",
            "再一個玉米蛋餅",
            session,
            "s1",
        )
    assert reg.add_item.call_args.kwargs["name"] == "玉米蛋餅"
