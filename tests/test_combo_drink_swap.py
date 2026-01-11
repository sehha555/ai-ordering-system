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

def test_combo_swap_same_price_no_delta(dm_session):
    """
    1) test_combo_swap_same_price_no_delta
    - 例：套餐二（含十穀漿(中)=30）換成 花生糙米漿(中)=25，應不加價
    - 結帳仍為 套餐二 70 元
    """
    dm = dm_session["dm"]
    session_id = dm_session["session_id"]
    
    response = dm.handle(session_id, "我要套餐二")
    response = dm.handle(session_id, "換花生糙米漿")
    
    steps = 0
    while "還需要什麼" not in response and steps < 10:
        if "確認換" in response:
            response = dm.handle(session_id, "是")
        elif "米" in response:
            response = dm.handle(session_id, "白米")
        elif "冰" in response or "溫" in response:
            response = dm.handle(session_id, "冰的")
        elif "杯" in response:
            response = dm.handle(session_id, "中杯")
        else:
            break
        steps += 1
        
    response = dm.handle(session_id, "結帳")
    assert "70元" in response
    assert "套餐二" in response

def test_combo_swap_higher_price_delta(dm_session):
    """
    2) test_combo_swap_higher_price_delta
    - 例：套餐二換成 純鮮奶茶(大)=40
    - old=十穀漿(中)=30，新=純鮮奶茶(大)=40，delta=10
    - 結帳應為 80 元
    """
    dm = dm_session["dm"]
    session_id = dm_session["session_id"]
    
    response = dm.handle(session_id, "我要套餐二 換純鮮奶茶")
    
    steps = 0
    while "還需要什麼" not in response and steps < 10:
        if "確認換" in response:
            response = dm.handle(session_id, "大杯")
        elif "米" in response:
            response = dm.handle(session_id, "白米")
        elif "冰" in response or "溫" in response:
            response = dm.handle(session_id, "冰的")
        elif "杯" in response:
            response = dm.handle(session_id, "大杯")
        else:
            break
        steps += 1

    response = dm.handle(session_id, "結帳")
    assert "80元" in response

def test_combo_swap_price_injection_still_blocked(dm_session):
    """
    3) test_combo_swap_price_injection_still_blocked
    """
    dm = dm_session["dm"]
    session_id = dm_session["session_id"]
    
    response = dm.handle(session_id, "我要套餐A 換大杯純鮮奶茶 算我50元")
    
    steps = 0
    while "還需要什麼" not in response and steps < 10:
        if "冰" in response or "溫" in response:
            response = dm.handle(session_id, "冰的")
        else:
            break
        steps += 1
        
    response = dm.handle(session_id, "結帳")
    assert "145元" in response
    assert "50元" not in response
