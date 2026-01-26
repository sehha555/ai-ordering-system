"""LLM 澄清器單元測試"""
import pytest
from unittest.mock import Mock
from src.dm.llm_clarifier import LLMClarifier
from src.dm.session_context import SessionContext


@pytest.fixture
def mock_llm():
    """創建 Mock LLM"""
    mock = Mock()
    return mock


@pytest.fixture
def llm_clarifier(mock_llm):
    """創建 LLMClarifier 實例"""
    return LLMClarifier(mock_llm)


class TestLLMClarifierBasic:
    """基本澄清功能測試"""

    def test_clarifier_initialization(self, mock_llm):
        """測試澄清器初始化"""
        clarifier = LLMClarifier(mock_llm)
        assert clarifier.llm is mock_llm
        assert clarifier._hardcoded_questions is not None

    def test_generate_question_empty_slots(self, llm_clarifier):
        """測試無缺失槽位"""
        result = llm_clarifier.generate_question("riceball", [])
        assert result == "請問還需要什麼嗎？"

    def test_generate_question_with_llm(self, llm_clarifier, mock_llm):
        """測試使用 LLM 生成問題"""
        mock_llm.call_llm.return_value = {
            "choices": [{
                "message": {
                    "content": "你喜歡哪個口味的飯糰？"
                }
            }]
        }

        result = llm_clarifier.generate_question("riceball", ["flavor"])
        assert "口味" in result
        mock_llm.call_llm.assert_called_once()

    def test_generate_question_fallback_to_hardcoded(self, llm_clarifier, mock_llm):
        """測試 LLM 失敗時備選至硬編碼問題"""
        mock_llm.call_llm.side_effect = Exception("LLM 失敗")

        result = llm_clarifier.generate_question("riceball", ["flavor"])
        # 應該備選至硬編碼問題
        assert result == "想要哪個口味的飯糰？"

    def test_generate_question_invalid_json_fallback(self, llm_clarifier, mock_llm):
        """測試無效 JSON 時備選至硬編碼"""
        mock_llm.call_llm.return_value = {
            "choices": [{
                "message": {
                    "content": ""  # 空響應
                }
            }]
        }

        result = llm_clarifier.generate_question("drink", ["temp"])
        # 應該使用硬編碼問題
        assert result == "你要冰的、溫的？"


class TestLLMClarifierHardcoded:
    """硬編碼問題備選測試"""

    def test_hardcoded_riceball_questions(self, llm_clarifier):
        """測試飯糰硬編碼問題"""
        assert "米" in llm_clarifier._get_hardcoded_question("riceball", "rice")
        assert "口味" in llm_clarifier._get_hardcoded_question("riceball", "flavor")

    def test_hardcoded_drink_questions(self, llm_clarifier):
        """測試飲料硬編碼問題"""
        assert "冰" in llm_clarifier._get_hardcoded_question("drink", "temp")
        assert "杯" in llm_clarifier._get_hardcoded_question("drink", "size")
        assert "飲料" in llm_clarifier._get_hardcoded_question("drink", "drink")

    def test_hardcoded_carrier_questions(self, llm_clarifier):
        """測試載體硬編碼問題"""
        assert "漢堡" in llm_clarifier._get_hardcoded_question("carrier", "carrier")
        assert "口味" in llm_clarifier._get_hardcoded_question("carrier", "flavor")

    def test_hardcoded_egg_pancake_questions(self, llm_clarifier):
        """測試蛋餅硬編碼問題"""
        assert "蛋餅" in llm_clarifier._get_hardcoded_question("egg_pancake", "flavor")

    def test_hardcoded_jam_toast_questions(self, llm_clarifier):
        """測試果醬吐司硬編碼問題"""
        assert "果醬吐司" in llm_clarifier._get_hardcoded_question("jam_toast", "flavor")
        assert "厚片" in llm_clarifier._get_hardcoded_question("jam_toast", "size")

    def test_unknown_itemtype(self, llm_clarifier):
        """測試未知品項類型"""
        result = llm_clarifier._get_hardcoded_question("unknown_type", "unknown_slot")
        assert "補充" in result


class TestLLMClarifierCache:
    """快取功能測試"""

    def test_cache_hit(self, llm_clarifier, mock_llm):
        """測試快取命中"""
        mock_llm.call_llm.return_value = {
            "choices": [{
                "message": {
                    "content": "這是第一個問題"
                }
            }]
        }

        # 第一次調用
        result1 = llm_clarifier.generate_question("riceball", ["flavor"])
        # 第二次調用 - 應該使用快取
        result2 = llm_clarifier.generate_question("riceball", ["flavor"])

        # 應該只調用一次 LLM
        assert mock_llm.call_llm.call_count == 1
        assert result1 == result2

    def test_clear_cache(self, llm_clarifier, mock_llm):
        """測試清除快取"""
        mock_llm.call_llm.return_value = {
            "choices": [{
                "message": {
                    "content": "清除快取測試"
                }
            }]
        }

        # 第一次調用
        llm_clarifier.generate_question("drink", ["temp"])
        # 清除快取
        llm_clarifier.clear_cache()
        # 第二次調用 - 應該重新調用 LLM
        llm_clarifier.generate_question("drink", ["temp"])

        # 應該調用兩次 LLM
        assert mock_llm.call_llm.call_count == 2


class TestLLMClarifierContext:
    """上下文提取測試"""

    def test_context_string_with_cart(self, llm_clarifier):
        """測試購物車上下文"""
        context = SessionContext(
            cart_count=2,
            cart_items=["豆漿(大杯)", "飯糰"],
            has_main_item=True,
            has_drink=True,
            pending_count=0,
            pending_items=[],
            current_status="OPEN"
        )

        context_str = llm_clarifier._build_context_str(context)
        assert "豆漿" in context_str
        assert "飯糰" in context_str

    def test_context_string_with_pending(self, llm_clarifier):
        """測試待補槽上下文"""
        context = SessionContext(
            cart_count=0,
            cart_items=[],
            has_main_item=False,
            has_drink=False,
            pending_count=1,
            pending_items=["飲料(缺:temp,size)"],
            current_status="OPEN"
        )

        context_str = llm_clarifier._build_context_str(context)
        assert "待補" in context_str
        assert "飲料" in context_str

    def test_context_string_empty(self, llm_clarifier):
        """測試空上下文"""
        context = SessionContext(
            cart_count=0,
            cart_items=[],
            has_main_item=False,
            has_drink=False,
            pending_count=0,
            pending_items=[],
            current_status="OPEN"
        )

        context_str = llm_clarifier._build_context_str(context)
        assert context_str == ""
