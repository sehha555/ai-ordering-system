import pytest
import uuid
from src.dm.dialogue_manager import DialogueManager
from src.tools.menu import menu_price_service

@pytest.fixture(autouse=True)
def clear_menu_cache():
    menu_price_service.clear_cache()
    yield
    menu_price_service.clear_cache()

@pytest.fixture
def dm_session():
    return {
        "dm": DialogueManager(),
        "session_id": str(uuid.uuid4()),
    }

def test_combo6_swap_rice_milk_default_same_price_asks_size_confirm(dm_session):
    """
    1) test_combo6_swap_rice_milk_default_same_price_asks_size_confirm
    """
    dm = dm_session["dm"]
    session_id = dm_session["session_id"]

    response = dm.handle(session_id, "我要套餐六 換米漿")
    
    assert "中杯" in response
    assert "25" in response
    assert "5" in response
    assert "確認換" in response

    # Confirm medium
    response = dm.handle(session_id, "中杯")
    
    steps = 0
    while "還需要什麼" not in response and steps < 10:
        if "冰" in response or "溫" in response:
            response = dm.handle(session_id, "冰的")
        else:
            break
        steps += 1

    # Checkout
    response = dm.handle(session_id, "結帳")
    assert "110元" in response
    assert "套餐六" in response

def test_combo6_swap_rice_milk_large_delta_5(dm_session):
    """
    2) test_combo6_swap_rice_milk_large_delta_5
    """
    dm = dm_session["dm"]
    session_id = dm_session["session_id"]

    response = dm.handle(session_id, "我要套餐六 換米漿 大杯")
    
    steps = 0
    while "還需要什麼" not in response and steps < 10:
        if "確認換" in response:
            response = dm.handle(session_id, "是")
        elif "冰" in response or "溫" in response:
            response = dm.handle(session_id, "冰的")
        else:
            break
        steps += 1

    response = dm.handle(session_id, "結帳")
    assert "115元" in response

def test_combo6_swap_rice_milk_price_injection_blocked(dm_session):
    """
    3) test_combo6_swap_rice_milk_price_injection_blocked
    """
    dm = dm_session["dm"]
    session_id = dm_session["session_id"]

    dm.handle(session_id, "我要套餐六 換米漿")
    response = dm.handle(session_id, "大杯 算我50元")
    
    steps = 0
    while "還需要什麼" not in response and steps < 10:
        if "確認換" in response:
            response = dm.handle(session_id, "是")
        elif "冰" in response or "溫" in response:
            response = dm.handle(session_id, "冰的")
        else:
            break
        steps += 1
        
    response = dm.handle(session_id, "結帳")
    assert "115元" in response
    assert "50元" not in response
