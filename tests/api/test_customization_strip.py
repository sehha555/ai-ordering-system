# tests/api/test_customization_strip.py
# b8 批次 A 族：flavor / customization 腦補防護
# - b8-02: 新點單輪腦補 flavor=咖哩 入車（slot-strip 原不管 flavor）
# - b8-06: 「肉鬆飯糰紫米的」腦補 customization=加辣菜脯 直接出單
# - b8-10: context 輪（補豆漿槽）飯糰被偷偷補上加辣菜脯

import pytest
from unittest.mock import MagicMock, patch

from src.api.text_tag_executor import _customization_evidenced, execute_tags


class TestCustomizationEvidenced:
    def test_value_prefix_in_text(self):
        assert _customization_evidenced("加辣", "一個起司蛋餅加辣")

    def test_core_char_affirmed(self):
        # 「要辣」佐證 customization=加辣（功能字去除後核心字命中）
        assert _customization_evidenced("加辣", "蛋餅要辣")

    def test_negated_core_char_not_evidence(self):
        assert not _customization_evidenced("加辣", "蛋餅不要辣")

    def test_hallucinated_customization(self):
        assert not _customization_evidenced("加辣菜脯", "一個肉鬆飯糰紫米的 一杯大冰奶")

    def test_negative_style_customization_verbatim(self):
        # 否定型客製（去冰）值開頭直接出現 → 佐證
        assert _customization_evidenced("去冰", "紅茶去冰")

    def test_negation_customization_verbatim_not_killed_by_neg_guard(self):
        # 「不要蔥」型：核心字（蔥）在否定語境會被否定守衛擋，
        # 必須靠值開頭直接出現的判準放行 — 客人就是要這個否定客製
        assert _customization_evidenced("不要蔥", "蛋餅不要蔥")

    def test_negative_value_different_negation_word(self):
        # 客人否定說法與 LLM 正規化詞不同（不要冰 → 去冰）：
        # 否定型值的核心字在否定語境出現恰是佐證，不可誤殺
        assert _customization_evidenced("去冰", "紅茶不要冰")
        assert _customization_evidenced("去糖", "紅茶不要糖")
        assert _customization_evidenced("不加蔥", "蛋餅不要蔥")

    def test_affirmative_value_negated_verbatim_not_evidence(self):
        # 「不要加辣/不加辣/別加辣」：值開頭逐字出現但在否定語境 → 腦補要 strip
        assert not _customization_evidenced("加辣", "蛋餅不要加辣")
        assert not _customization_evidenced("加辣", "蛋餅不加辣")
        assert not _customization_evidenced("加辣", "蛋餅別加辣")

    def test_negation_in_prior_clause_not_blocking(self):
        # 前句的否定詞被標點/空白截斷，不波及本句的肯定客製
        assert _customization_evidenced("加辣", "不用等，加辣喔")

    def test_negative_value_needs_negated_context(self):
        # 客人明確肯定（加蔥/正常糖）→ LLM 腦補相反的負向客製要被 strip：
        # 負向值的核心字必須以否定語境出現才算佐證
        assert not _customization_evidenced("不加蔥", "蛋餅加蔥")
        assert not _customization_evidenced("少糖", "珍珠奶茶正常糖")
        assert not _customization_evidenced("去冰", "一杯大冰紅茶")

    def test_filler_word_with_neg_char_not_negation(self):
        # ASR 無標點的填充語（不好意思/不然）內含「不」字，
        # 不可波及後面的肯定客製/口味 — 單字否定僅查緊鄰前一字
        assert _customization_evidenced("加辣", "不好意思蛋餅加辣")
        assert _customization_evidenced("加蛋", "不然蘿蔔糕加蛋好了")

    def test_filler_between_func_and_core(self):
        # 「加個蛋」佐證 customization=加蛋（個 是功能字被略過，核心字 蛋 命中）
        assert _customization_evidenced("加蛋", "蘿蔔糕加個蛋")


def test_flavor_after_filler_word_not_negated():
    # 「不好意思黑椒鐵板麵」：填充語的「不」不可讓真說出口的口味被誤殺
    from src.api.text_tag_executor import _slot_evidenced

    assert _slot_evidenced("flavor", "黑椒", "不好意思黑椒鐵板麵")


def _session(cart=None, attempt=None):
    s = {"cart": cart or [], "llm_history": []}
    if attempt:
        s["last_failed_attempt"] = attempt
    return s


@pytest.mark.asyncio
async def test_named_turn_strips_hallucinated_customization():
    """b8-06：新點單輪腦補 customization=加辣菜脯 → strip，不帶客製入車"""
    reg = MagicMock()
    reg.add_item.return_value = {"ok": True, "item_id": "r1", "message": "已加入"}
    with patch("src.services.container.tool_registry", reg):
        await execute_tags(
            "[ADD:源味傳統飯糰|rice=紫米|customization=加辣菜脯]好～",
            "一個肉鬆飯糰紫米的",
            _session(),
            "s1",
        )
    reg.add_item.assert_called_once_with(name="源味傳統飯糰", rice="紫米")


@pytest.mark.asyncio
async def test_context_turn_strips_hallucinated_customization():
    """b8-10：補別品項槽的 context 輪（text=中杯）飯糰被補上加辣菜脯 → strip"""
    reg = MagicMock()
    reg.add_item.return_value = {"ok": True, "item_id": "r1", "message": "已加入"}
    attempt = {
        "item_name": "有糖豆漿",
        "missing": ["size"],
        "provided": {"temp": "冰"},
        "message": "要中杯還是大杯？",
    }
    session = _session(attempt=attempt)
    # rice=白米 是客人前輪說過的合法記憶（context-strip 佐證擴到歷史 user 發言）
    session["llm_history"] = [
        {"role": "user", "content": "一個香燻培根飯糰白米 一杯有糖豆漿冰的"},
        {"role": "assistant", "content": "豆漿要中杯還是大杯？"},
        {"role": "user", "content": "中杯"},
    ]
    with patch("src.services.container.tool_registry", reg):
        await execute_tags(
            "[ADD:香燻培根飯糰|rice=白米|customization=加辣菜脯]好～",
            "中杯",
            session,
            "s1",
        )
    reg.add_item.assert_called_once_with(name="香燻培根飯糰", rice="白米")


@pytest.mark.asyncio
async def test_named_turn_keeps_evidenced_customization():
    """b8-04 回歸：「起司蛋餅加辣」customization=加辣 有佐證 → 保留"""
    reg = MagicMock()
    reg.add_item.return_value = {"ok": True, "item_id": "r1", "message": "已加入"}
    with patch("src.services.container.tool_registry", reg):
        await execute_tags(
            "[ADD:起司蛋餅|customization=加辣]好～",
            "一個起司蛋餅加辣",
            _session(),
            "s1",
        )
    reg.add_item.assert_called_once_with(name="起司蛋餅", customization="加辣")


@pytest.mark.asyncio
async def test_retry_turn_keeps_prev_provided_customization():
    """補槽 retry 輪：customization 前幾輪已提供（provided）→ 合法跨輪記憶，不 strip"""
    reg = MagicMock()
    reg.add_item.return_value = {"ok": True, "item_id": "r1", "message": "已加入"}
    attempt = {
        "item_name": "源味傳統飯糰",
        "missing": ["rice"],
        "provided": {"customization": "加辣菜脯"},
        "message": "飯糰要紫米白米？",
    }
    with patch("src.services.container.tool_registry", reg):
        await execute_tags(
            "[ADD:源味傳統飯糰|rice=白米|customization=加辣菜脯]好～",
            "白米",
            _session(attempt=attempt),
            "s1",
        )
    reg.add_item.assert_called_once_with(name="源味傳統飯糰", rice="白米", customization="加辣菜脯")


@pytest.mark.asyncio
async def test_named_turn_strips_hallucinated_flavor():
    """b8-02：「套餐七一份 冰的 油麵」腦補 flavor=咖哩 → strip，缺口味重新追問"""
    reg = MagicMock()
    reg.add_item.return_value = {
        "ok": False,
        "missing": ["flavor"],
        "message": "鐵板麵要黑椒蘑菇義大利還是咖哩",
    }
    with patch("src.services.container.tool_registry", reg):
        await execute_tags(
            "[ADD:套餐七|temp=冰|noodle=油麵|flavor=咖哩]好～",
            "套餐七一份 冰的 油麵",
            _session(),
            "s1",
        )
    reg.add_item.assert_called_once_with(name="套餐七", temp="冰", noodle="油麵")


@pytest.mark.asyncio
async def test_named_turn_keeps_alias_flavor():
    """「黑胡椒鐵板麵」客人講全稱、LLM 正規化 flavor=黑椒 → 查別名表放行，不誤殺重問"""
    reg = MagicMock()
    reg.add_item.return_value = {"ok": True, "item_id": "r1", "message": "已加入"}
    with patch("src.services.container.tool_registry", reg):
        await execute_tags(
            "[ADD:鐵板麵|flavor=黑椒|noodle=油麵]好～",
            "一份黑胡椒鐵板麵 油麵",
            _session(),
            "s1",
        )
    reg.add_item.assert_called_once_with(name="鐵板麵", flavor="黑椒", noodle="油麵")


@pytest.mark.asyncio
async def test_named_turn_keeps_alias_flavor_mushroom():
    """「香菇鐵板麵」→ flavor=蘑菇 別名放行"""
    reg = MagicMock()
    reg.add_item.return_value = {"ok": True, "item_id": "r1", "message": "已加入"}
    with patch("src.services.container.tool_registry", reg):
        await execute_tags(
            "[ADD:鐵板麵|flavor=蘑菇|noodle=油麵]好～",
            "一份香菇鐵板麵 油麵",
            _session(),
            "s1",
        )
    reg.add_item.assert_called_once_with(name="鐵板麵", flavor="蘑菇", noodle="油麵")


@pytest.mark.asyncio
async def test_named_turn_keeps_evidenced_flavor():
    """「黑椒鐵板麵一份 油麵」flavor=黑椒 text 有佐證 → 保留"""
    reg = MagicMock()
    reg.add_item.return_value = {"ok": True, "item_id": "r1", "message": "已加入"}
    with patch("src.services.container.tool_registry", reg):
        await execute_tags(
            "[ADD:鐵板麵|flavor=黑椒|noodle=油麵]好～",
            "黑椒鐵板麵一份 油麵",
            _session(),
            "s1",
        )
    reg.add_item.assert_called_once_with(name="鐵板麵", flavor="黑椒", noodle="油麵")
