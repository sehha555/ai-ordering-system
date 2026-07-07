# tests/api/test_combo_noodle_slot.py
# b6-04 套餐鐵板麵兩缺口：
# 1. combo 沒有 noodle 槽 — 客人說「烏龍麵」被丟掉，店員做餐還得再問
# 2. 補槽輪 LLM 腦補沒被問到的槽（「烏龍麵 冰的」→ flavor=黑椒 出錯餐）

import pytest
from unittest.mock import MagicMock, patch

from src.api.text_tag_executor import execute_tags
from src.dm import cart_manager
from src.dm.tool_registry import ToolRegistry
from src.dm.dialogue_manager import DialogueManager
from src.dm.session_store import InMemorySessionStore


@pytest.fixture
def registry():
    store = InMemorySessionStore()
    dm = DialogueManager(llm=None, store=store)
    tr = ToolRegistry(dm, store)
    tr.set_session_id("noodle-test")
    return tr, store


class TestComboNoodleSlot:
    def test_combo_six_missing_noodle_asks(self, registry):
        tr, _ = registry
        result = tr.add_item(name="套餐六", temp="冰", flavor="黑椒")
        assert not result["ok"]
        assert "noodle" in result["missing"]
        assert "油麵" in result["message"] and "烏龍" in result["message"]

    def test_combo_six_with_noodle_stores_and_displays(self, registry):
        tr, store = registry
        result = tr.add_item(name="套餐六", temp="冰", flavor="黑椒", noodle="烏龍麵")
        assert result["ok"]
        item = store.get("noodle-test")["cart"][0]
        assert item["noodle"] == "烏龍麵"
        assert cart_manager.format_item(item) == "套餐六(黑椒, 烏龍麵, 冰)"

    def test_other_combos_not_affected(self, registry):
        tr, _ = registry
        result = tr.add_item(name="套餐三", temp="冰")
        assert result["ok"]


def _retry_session():
    """套餐六補槽中：temp 前輪已提供，缺 flavor/noodle"""
    return {
        "cart": [],
        "llm_history": [
            {"role": "user", "content": "一個套餐六 冰的"},
            {"role": "assistant", "content": "鐵板麵要黑椒蘑菇義大利還是咖哩 油麵還是烏龍麵"},
        ],
        "last_failed_attempt": {
            "item_name": "套餐六",
            "missing": ["flavor", "noodle"],
            "provided": {"temp": "冰"},
            "message": "鐵板麵要黑椒蘑菇義大利還是咖哩 鐵板麵要油麵還是烏龍麵",
        },
    }


@pytest.mark.asyncio
async def test_retry_turn_strips_unevidenced_flavor():
    """補槽輪「烏龍麵」：noodle 有佐證保留、temp 前輪已提供保留、flavor=黑椒 腦補 strip"""
    reg = MagicMock()
    reg.add_item.return_value = {
        "ok": False,
        "missing": ["flavor"],
        "message": "鐵板麵要黑椒蘑菇義大利還是咖哩",
    }
    session = _retry_session()
    with patch("src.services.container.tool_registry", reg):
        await execute_tags(
            "[ADD:套餐六|temp=冰|flavor=黑椒|noodle=烏龍麵]好～",
            "烏龍麵",
            session,
            "s1",
        )
    reg.add_item.assert_called_once_with(name="套餐六", temp="冰", noodle="烏龍麵")


@pytest.mark.asyncio
async def test_retry_turn_keeps_evidenced_flavor():
    """補槽輪「蘑菇的 烏龍麵」：flavor=蘑菇 有佐證保留 → 入車成功"""
    reg = MagicMock()
    reg.add_item.return_value = {"ok": True, "item_id": "combo_1", "message": "已加入"}
    session = _retry_session()
    with patch("src.services.container.tool_registry", reg):
        await execute_tags(
            "[ADD:套餐六|temp=冰|flavor=蘑菇|noodle=烏龍麵]好～",
            "蘑菇的 烏龍麵",
            session,
            "s1",
        )
    reg.add_item.assert_called_once_with(name="套餐六", temp="冰", flavor="蘑菇", noodle="烏龍麵")


@pytest.mark.asyncio
async def test_retry_turn_negated_value_not_evidence():
    """補槽輪「不要黑椒 烏龍麵」：黑椒在否定語境，不算 flavor=黑椒 的佐證 → strip"""
    reg = MagicMock()
    reg.add_item.return_value = {
        "ok": False,
        "missing": ["flavor"],
        "message": "鐵板麵要黑椒蘑菇義大利還是咖哩",
    }
    session = _retry_session()
    with patch("src.services.container.tool_registry", reg):
        await execute_tags(
            "[ADD:套餐六|temp=冰|flavor=黑椒|noodle=烏龍麵]好～",
            "不要黑椒 烏龍麵",
            session,
            "s1",
        )
    reg.add_item.assert_called_once_with(name="套餐六", temp="冰", noodle="烏龍麵")


@pytest.mark.asyncio
async def test_named_turn_not_affected_by_retry_strip():
    """text 有點名品項的正常點單輪走原 slot-strip，不走補槽防護"""
    reg = MagicMock()
    reg.add_item.return_value = {"ok": True, "item_id": "combo_1", "message": "已加入"}
    session = _retry_session()
    with patch("src.services.container.tool_registry", reg):
        await execute_tags(
            "[ADD:套餐六|temp=冰|flavor=黑椒|noodle=烏龍麵]好～",
            "一個套餐六 冰的黑椒烏龍麵",
            session,
            "s1",
        )
    reg.add_item.assert_called_once_with(name="套餐六", temp="冰", flavor="黑椒", noodle="烏龍麵")
