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

def test_order_large_iced_milk_tea_success(dm_session):
    """
    Test ordering "大冰奶" successfully and verifying its price.
    "大冰奶" should map to "純鮮奶茶", size "大杯", temp "冰". Price 40.
    """
    dm = dm_session["dm"]
    session_id = dm_session["session_id"]

    response = dm.handle(session_id, "我要一杯大冰奶")
    assert "已加入" in response
    assert "純鮮奶茶" in response
    assert "大杯" in response
    assert "冰" in response
    assert "還需要什麼嗎？" in response

    response = dm.handle(session_id, "結帳")
    assert "這樣一共" in response
    assert "40元" in response

def test_order_medium_unsweetened_soy_milk_success(dm_session):
    """
    Test ordering "無糖豆漿中杯" successfully, providing missing info, and verifying its price.
    """
    dm = dm_session["dm"]
    session_id = dm_session["session_id"]

    # User orders, DM asks for temp
    response = dm.handle(session_id, "我要一杯無糖豆漿中杯")
    assert "你要冰的、溫的？" in response
    
    # Provide missing temp
    response = dm.handle(session_id, "冰的")
    assert "已加入" in response
    assert "中杯 冰" in response
    assert "還需要什麼嗎？" in response

    # Checkout
    response = dm.handle(session_id, "結帳")
    assert "這樣一共" in response
    assert "20元" in response

def test_order_two_large_hot_brown_sugar_milk_tea_success(dm_session):
    """
    Test ordering "兩杯熱黑糖奶茶大杯" successfully and verifying its price.
    "黑糖奶茶" should map to "黑糖純鮮奶茶", size "大杯", temp "熱", quantity 2. Price 45*2 = 90.
    """
    dm = dm_session["dm"]
    session_id = dm_session["session_id"]

    response = dm.handle(session_id, "我要兩杯熱黑糖奶茶大杯")
    assert "已加入" in response
    assert "黑糖純鮮奶茶" in response
    assert "大杯" in response
    assert "熱" in response
    assert "還需要什麼嗎？" in response

    response = dm.handle(session_id, "結帳")
    assert "這樣一共" in response
    assert "90元" in response

def test_order_shortcut_large_iced_milk_tea(dm_session):
    """測試 "大冰奶" => size 大杯, temp 冰"""
    dm = dm_session["dm"]
    session_id = dm_session["session_id"]

    response = dm.handle(session_id, "我要一杯大冰奶")
    assert "已加入" in response
    assert "純鮮奶茶" in response
    assert "大杯" in response
    assert "冰" in response

def test_order_shortcut_small_hot_soy_milk(dm_session):
    """測試 "小熱豆" => size 中杯, temp 熱"""
    dm = dm_session["dm"]
    session_id = dm_session["session_id"]

    response = dm.handle(session_id, "我要一杯小熱豆")
    assert "已加入" in response
    assert "有糖豆漿" in response
    assert "中杯" in response
    assert "熱" in response

def test_order_shortcut_medium_warm_red_tea(dm_session):
    """測試 "中溫紅" => size 中杯, temp 溫"""
    dm = dm_session["dm"]
    session_id = dm_session["session_id"]

    response = dm.handle(session_id, "我要一杯中溫紅")
    assert "已加入" in response
    assert "精選紅茶" in response
    assert "中杯" in response
    assert "溫" in response
