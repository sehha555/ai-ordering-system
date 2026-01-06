import pytest
from src.dm.dialogue_manager import DialogueManager

@pytest.fixture
def dm():
    """Provides a DialogueManager instance for testing."""
    return DialogueManager()

@pytest.fixture
def session_id():
    """Provides a unique session ID for each test."""
    return "test-session-egg-pancake"

def test_order_egg_pancake_and_confirm(dm, session_id):
    """
    Case 1: 輸入「我要一個起司蛋餅」→ 回覆包含加入品項關鍵字
    """
    response = dm.handle(session_id, "我要一個起司蛋餅")
    assert "已加入" in response
    assert "起司蛋餅" in response

def test_checkout_egg_pancake(dm, session_id):
    """
    Case 2: 接著輸入「結帳」→ 回覆包含 40 元
    """
    dm.handle(session_id, "我要一個起司蛋餅")
    response = dm.handle(session_id, "結帳")
    assert "40元" in response
    assert "這樣一共" in response

def test_egg_pancake_riceball_routing_priority(dm, session_id):
    """
    Case 3: 輸入「我要蛋餅飯糰」→ 必須走飯糰流程
    """
    response = dm.handle(session_id, "我要蛋餅飯糰")
    # Assert that it asks for rice type, which is specific to the riceball tool flow.
    assert "米種" in response
