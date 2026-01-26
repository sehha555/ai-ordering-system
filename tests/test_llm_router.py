"""LLM 路由器單元測試"""
import pytest
from unittest.mock import Mock, MagicMock
from src.dm.llm_router import LLMRouter
from src.dm.session_context import SessionContext


@pytest.fixture
def mock_llm():
    """創建 Mock LLM"""
    mock = Mock()
    return mock


@pytest.fixture
def llm_router(mock_llm):
    """創建 LLMRouter 實例"""
    return LLMRouter(mock_llm, timeout=5, confidence_threshold=0.75)


class TestLLMRouterBasic:
    """基本路由功能測試"""

    def test_router_initialization(self, mock_llm):
        """測試路由器初始化"""
        router = LLMRouter(mock_llm)
        assert router.llm is mock_llm
        assert router.timeout == 5
        assert router.confidence_threshold == 0.75

    def test_classify_with_valid_response(self, llm_router, mock_llm):
        """測試分類成功的情況"""
        # 模擬 LLM 響應
        mock_llm.call_llm.return_value = {
            "choices": [{
                "message": {
                    "content": '{"route_type": "riceball", "confidence": 0.9, "reasoning": "客人說飯糰", "alternatives": []}'
                }
            }]
        }

        result = llm_router.classify("我要飯糰")
        assert result["route_type"] == "riceball"
        assert result["confidence"] == 0.9
        assert "飯糰" in result["reasoning"]

    def test_classify_with_low_confidence(self, llm_router, mock_llm):
        """測試信心度低的分類"""
        mock_llm.call_llm.return_value = {
            "choices": [{
                "message": {
                    "content": '{"route_type": "drink", "confidence": 0.3, "reasoning": "不確定", "alternatives": ["riceball"]}'
                }
            }]
        }

        result = llm_router.classify("我要米漿")
        # 信心度低於閾值，但仍會返回結果（決定由調用者做）
        assert result["confidence"] == 0.3
        assert result["route_type"] == "drink"

    def test_classify_unknown_result(self, llm_router, mock_llm):
        """測試分類為未知"""
        mock_llm.call_llm.return_value = {
            "choices": [{
                "message": {
                    "content": '{"route_type": "unknown", "confidence": 0.2, "reasoning": "無法判斷", "alternatives": []}'
                }
            }]
        }

        result = llm_router.classify("xyz 什麼東西")
        assert result["route_type"] == "unknown"
        assert result["confidence"] == 0.2

    def test_classify_with_invalid_json(self, llm_router, mock_llm):
        """測試無效 JSON 響應處理"""
        mock_llm.call_llm.return_value = {
            "choices": [{
                "message": {
                    "content": "這不是 JSON"
                }
            }]
        }

        result = llm_router.classify("無法解析")
        assert result["route_type"] == "unknown"
        assert result["confidence"] == 0.0
        assert "trace" in result

    def test_classify_with_exception(self, llm_router, mock_llm):
        """測試異常處理"""
        mock_llm.call_llm.side_effect = Exception("LLM 連線失敗")

        result = llm_router.classify("會失敗的輸入")
        assert result["route_type"] == "unknown"
        assert result["confidence"] == 0.0
        assert "error" in result["trace"]


class TestLLMRouterCache:
    """快取功能測試"""

    def test_cache_hit(self, llm_router, mock_llm):
        """測試快取命中"""
        mock_llm.call_llm.return_value = {
            "choices": [{
                "message": {
                    "content": '{"route_type": "riceball", "confidence": 0.9, "reasoning": "快取", "alternatives": []}'
                }
            }]
        }

        # 第一次調用
        result1 = llm_router.classify("我要飯糰")
        # 第二次調用 - 應該使用快取
        result2 = llm_router.classify("我要飯糰")

        # 應該只調用一次 LLM
        assert mock_llm.call_llm.call_count == 1
        assert result1 == result2

    def test_clear_cache(self, llm_router, mock_llm):
        """測試清除快取"""
        mock_llm.call_llm.return_value = {
            "choices": [{
                "message": {
                    "content": '{"route_type": "riceball", "confidence": 0.9, "reasoning": "清除快取", "alternatives": []}'
                }
            }]
        }

        # 第一次調用
        llm_router.classify("我要飯糰")
        # 清除快取
        llm_router.clear_cache()
        # 第二次調用 - 應該重新調用 LLM
        llm_router.classify("我要飯糰")

        # 應該調用兩次 LLM
        assert mock_llm.call_llm.call_count == 2


class TestLLMRouterContext:
    """上下文提取測試"""

    def test_classify_with_session_context(self, llm_router, mock_llm):
        """測試使用會話上下文的分類"""
        # 創建會話上下文
        session = {
            "cart": [{"itemtype": "riceball", "flavor": "鮪魚"}],
            "pending_frames": [],
            "status": "OPEN"
        }
        context = SessionContext.from_session(session)

        mock_llm.call_llm.return_value = {
            "choices": [{
                "message": {
                    "content": '{"route_type": "drink", "confidence": 0.85, "reasoning": "根據上下文", "alternatives": []}'
                }
            }]
        }

        result = llm_router.classify("再來一杯豆漿", session_context=context)
        assert result["route_type"] == "drink"
        # 驗證上下文被傳遞
        mock_llm.call_llm.assert_called_once()
