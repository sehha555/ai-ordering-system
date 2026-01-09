import pytest
import uuid
from src.dm.dialogue_manager import DialogueManager
from src.tools.menu import menu_price_service

@pytest.fixture(autouse=True)
def clear_menu_cache():
    """Fixture to automatically clear the menu service cache before each test."""
    menu_price_service.clear_cache()
    yield
    menu_price_service.clear_cache()

@pytest.fixture
def dm_session():
    """Fixture to create a new DialogueManager and session ID for each test."""
    return {
        "dm": DialogueManager(),
        "session_id": str(uuid.uuid4()),
    }

def test_order_ham_egg_toast_success(dm_session):
    """
    Test ordering "火腿蛋吐司" successfully and verifying its price.
    """
    dm = dm_session["dm"]
    session_id = dm_session["session_id"]

    # User orders ham egg toast
    response = dm.handle(session_id, "我要一個火腿蛋吐司")
    assert "好的，1份 火腿蛋吐司，還需要什麼嗎？" in response

    # Checkout
    response = dm.handle(session_id, "結帳")
    assert "這樣一共" in response
    assert "40元" in response

def test_order_pork_egg_burger_success(dm_session):
    """
    Test ordering "豬肉蛋漢堡" successfully and verifying its price.
    """
    dm = dm_session["dm"]
    session_id = dm_session["session_id"]

    # User orders pork egg burger
    response = dm.handle(session_id, "我要豬肉蛋漢堡")
    assert "好的，1份 豬肉蛋漢堡，還需要什麼嗎？" in response

    # Checkout
    response = dm.handle(session_id, "結帳")
    assert "這樣一共" in response
    assert "50元" in response

def test_order_mantou_add_meat_success(dm_session):
    """
    Test ordering "饅頭夾蛋加肉片" which should infer to "醬燒肉片蛋饅頭" and verify its price.
    """
    dm = dm_session["dm"]
    session_id = dm_session["session_id"]

    # User orders mantou with egg and meat slices, which should be directly resolved.
    response = dm.handle(session_id, "我要饅頭夾蛋加肉片")
    assert "好的，1份 醬燒肉片蛋饅頭，還需要什麼嗎？" in response
    
    # Checkout
    response = dm.handle(session_id, "結帳")
    assert "這樣一共" in response
    assert "共 1 個品項" in response
    assert "65元" in response # Price of 醬燒肉片蛋饅頭
