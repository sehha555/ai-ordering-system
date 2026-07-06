"""拼音同音匹配（_resolve_item_name step 3.5）+ step 8/9 合併 regression

ASR 同音錯字（委魚→鮪魚、蠻頭→饅頭）不靠修正表，由無聲調拼音索引自動修正。
"""

import pytest

from src.dm.tool_registry import ToolRegistry
from src.dm.dialogue_manager import DialogueManager
from src.dm.session_store import InMemorySessionStore


@pytest.fixture
def registry():
    store = InMemorySessionStore()
    dm = DialogueManager(store=store)
    tr = ToolRegistry(dm, store)
    tr.set_session_id("pinyin-test")
    return tr


class TestPinyinHomophoneResolve:
    """同音錯字 → 正確菜單品項（修正表沒有這些變體，rapidfuzz 字面相似度也不夠）"""

    def test_homophone_riceball(self, registry):
        info = registry._resolve_item_name("委魚飯糰")
        assert info is not None
        assert info["resolved_name"] == "鮪魚飯糰"
        assert info["category"] == "飯糰"

    def test_homophone_mantou(self, registry):
        info = registry._resolve_item_name("黑糖蠻頭")
        assert info is not None
        assert info["resolved_name"] == "黑糖饅頭"

    def test_homophone_beats_ep_alias_fallback(self, registry):
        # 「企司蛋餅」全名同音於「起司蛋餅」，不該被蛋餅別名子字串匹配吃成原味蛋餅
        info = registry._resolve_item_name("企司蛋餅")
        assert info is not None
        assert info["resolved_name"] == "起司蛋餅"

    def test_unrelated_name_returns_none(self, registry):
        assert registry._resolve_item_name("牛肉麵") is None

    def test_homophone_add_item_integration(self, registry):
        result = registry.add_item(name="委魚飯糰", rice="白米")
        assert result["ok"] is True


class TestPinyinRecursionGuard:
    """拼音命中自己（base name 輸入）不得無限遞迴，由後續 step 正常接手"""

    def test_base_name_drink(self, registry):
        info = registry._resolve_item_name("有糖豆漿")
        assert info is not None
        assert info["category"] == "飲品"

    def test_base_name_iron_noodle(self, registry):
        info = registry._resolve_item_name("黑椒鐵板麵")
        assert info is not None
        assert info["resolved_name"] == "黑椒鐵板麵(油麵)+蛋"


class TestSubstringSubsequenceMerge:
    """step 8/9 合併後行為不變"""

    def test_substring_match(self, registry):
        # 子字串：「咔啦雞腿」⊂「原味咔啦雞腿」，長度比 4/6 >= 0.6
        info = registry._resolve_item_name("咔啦雞腿")
        assert info is not None
        assert info["resolved_name"] == "原味咔啦雞腿"

    def test_subsequence_match(self, registry):
        # 漏字：「煎吐司」字符按順序出現在「煎蛋吐司」
        info = registry._resolve_item_name("煎吐司")
        assert info is not None
        assert info["resolved_name"] == "煎蛋吐司"


class TestSpecBracketStrip:
    """LLM 腦補規格括號（「鮮肉包(8顆)」套煎餃格式）→ 去括號後仍能對回菜單實名"""

    def test_hallucinated_spec_bracket(self, registry):
        info = registry._resolve_item_name("鮮肉包(8顆)")
        assert info is not None
        assert info["resolved_name"] == "鮮肉包"

    def test_wrong_spec_on_real_item(self, registry):
        # 菜單實名「薯餅(1片)」，LLM 發錯規格 → 仍對回唯一的薯餅品項
        info = registry._resolve_item_name("薯餅(3片)")
        assert info is not None
        assert info["resolved_name"] == "薯餅(1片)"

    def test_multi_variant_base_picks_flavor_match(self, registry):
        # 果醬吐司 10 種變體同 base：括號口味資訊必須參與挑選，不能短路取第一個
        info = registry._resolve_item_name("果醬吐司(花生)")
        assert info is not None
        assert "花生" in info["resolved_name"]

    def test_multi_variant_base_picks_closest(self, registry):
        info = registry._resolve_item_name("蔥抓餅(雙蛋)")
        assert info is not None
        assert info["resolved_name"] == "蔥抓餅(加蛋)"
