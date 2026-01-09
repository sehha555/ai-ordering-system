# -*- coding: utf-8 -*-
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
    dm = DialogueManager()
    session_id = str(uuid.uuid4())
    # Session is created with new defaults automatically by InMemorySessionStore.get()
    return {
        "dm": dm,
        "session_id": session_id,
    }

def test_multi_item_all_complete(dm_session):
    """測試一句話點兩個都完整的品項，應直接加入購物車"""
    dm = dm_session["dm"]
    session_id = dm_session["session_id"]
    
    response = dm.handle(session_id, "我要大冰奶跟一份薯餅")
    assert "好的，1份 純鮮奶茶(大杯, 冰)、1份 薯餅(1片)，還需要什麼嗎？" in response
    
    session = dm.store.get(session_id)
    assert len(session["cart"]) == 2
    assert len(session["pending_frames"]) == 0
    assert session["cart"][0]["drink"] == "純鮮奶茶"
    assert session["cart"][1]["snack"] == "薯餅(1片)"
    
    response = dm.handle(session_id, "結帳")
    assert "這樣一共" in response
    assert "60元" in response # 40 + 20

def test_multi_item_one_pending(dm_session):
    """測試一句話點兩個，其中一個需要補槽"""
    dm = dm_session["dm"]
    session_id = dm_session["session_id"]

    response = dm.handle(session_id, "我要一杯豆漿跟一份薯餅")
    # It should ask for the first pending item, which is the drink
    assert "你要冰的、溫的？" in response
    
    session = dm.store.get(session_id)
    assert len(session["cart"]) == 1 # The complete item (hash brown) is in cart
    assert len(session["pending_frames"]) == 1
    assert session["cart"][0]["snack"] == "薯餅(1片)"
    assert session["pending_frames"][0]["drink"] == "有糖豆漿"

    # User provides missing info for the drink
    response = dm.handle(session_id, "冰的，中杯")
    assert "好的，1份 有糖豆漿(中杯, 冰)，還需要什麼嗎？" in response
    
    session = dm.store.get(session_id)
    assert len(session["cart"]) == 2
    assert len(session["pending_frames"]) == 0

    response = dm.handle(session_id, "結帳")
    assert "這樣一共" in response
    assert "40元" in response # 20 + 20

def test_multi_item_two_pending_and_queue(dm_session):
    """測試一句話點兩個都不完整的品項，應逐一追問"""
    dm = dm_session["dm"]
    session_id = dm_session["session_id"]

    response = dm.handle(session_id, "我要豆漿跟一個鮪魚蛋")
    # It should ask for the first pending item (drink)
    assert "你要冰的、溫的？" in response
    
    session = dm.store.get(session_id)
    assert len(session["cart"]) == 0
    assert len(session["pending_frames"]) == 2
    assert session["pending_frames"][0]["itemtype"] == "drink"
    assert session["pending_frames"][1]["itemtype"] == "carrier"

    # User answers for the first pending item (drink)
    response = dm.handle(session_id, "大杯冰的")
    # Now it should ask for the second pending item (carrier)
    assert "你要漢堡、吐司還是饅頭？" in response
    
    session = dm.store.get(session_id)
    assert len(session["cart"]) == 1 # drink is now in cart
    assert len(session["pending_frames"]) == 1
    assert session["cart"][0]["drink"] == "有糖豆漿"
    assert session["pending_frames"][0]["flavor"] == "鮪魚蛋"

    # User answers for the second pending item (carrier)
    response = dm.handle(session_id, "吐司")
    assert "好的，1份 鮪魚蛋吐司，還需要什麼嗎？" in response

    session = dm.store.get(session_id)
    assert len(session["cart"]) == 2
    assert len(session["pending_frames"]) == 0
    
    response = dm.handle(session_id, "結帳")
    assert "這樣一共" in response
    assert "80元" in response # 25 (drink) + 55 (carrier)