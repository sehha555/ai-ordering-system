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

def test_combo_A_id_match(dm_session):
    """
    A.1) 套餐編號命中: 套餐A
    Given 使用者輸入：我要套餐A
    Then 應進入套餐補槽流程
    And 最終結帳總價必須等於套餐A固定價 130 元
    """
    dm = dm_session["dm"]
    session_id = dm_session["session_id"]

    # 1. Order Combo A
    response = dm.handle(session_id, "我要套餐A")
    
    # Combo A includes "紅茶(大)", so it should ask for temp/sugar.
    # Other items might be opaque or complete.
    
    steps = 0
    # Handle potential questions for sub-items
    while "結帳" not in response and "元" not in response and steps < 5:
        if "還需要什麼" in response:
            break
        if "冰" in response or "溫" in response:
            response = dm.handle(session_id, "冰的")
        elif "口味" in response:
            response = dm.handle(session_id, "原味") # Fallback
        else:
            # If asking something else, try to proceed or break
            # Assume if we reached "Anything else?", we are done
             break
        steps += 1
    
    # 2. Checkout
    response = dm.handle(session_id, "結帳")
    # Must be 130
    assert "130元" in response
    assert "套餐A" in response

def test_kids_meal_id_match(dm_session):
    """
    A.2) 兒童餐
    Given 使用者輸入：我要兒童餐
    Then 最終結帳總價必須等於兒童餐固定價 85 元
    """
    dm = dm_session["dm"]
    session_id = dm_session["session_id"]
    
    response = dm.handle(session_id, "我要兒童餐")
    
    # Kids meal: 薯條+雞塊*4+果醬吐司+紅茶(中)
    # May ask for drink temp or toast flavor
    
    steps = 0
    while "結帳" not in response and "元" not in response and steps < 5:
        if "還需要什麼" in response:
            break
            
        if "冰" in response or "溫" in response:
            response = dm.handle(session_id, "冰的")
        elif "口味" in response: # For Jam Toast?
            response = dm.handle(session_id, "草莓")
        elif "厚片" in response or "薄片" in response:
            response = dm.handle(session_id, "薄片")
        else:
             break
        steps += 1
        
    response = dm.handle(session_id, "結帳")
    assert "85元" in response

def test_combo_two_content_match(dm_session):
    """
    B.3) 套餐二內容命中
    Given 使用者輸入：我要源味飯糰加十穀漿
    Then 系統應命中「套餐二 源味飯糰+十穀漿(中)」
    And 最終結帳總價等於套餐二固定價 70 元
    """
    dm = dm_session["dm"]
    session_id = dm_session["session_id"]
    
    response = dm.handle(session_id, "我要源味飯糰加十穀漿")
    
    # Should identify Combo Two.
    # Riceball needs rice. Drink needs temp.
    
    if "米" in response:
        response = dm.handle(session_id, "白米")
    
    # Might ask for drink temp next
    if "冰" in response or "溫" in response:
        response = dm.handle(session_id, "冰的")
        
    response = dm.handle(session_id, "結帳")
    assert "70元" in response
    assert "套餐二" in response

def test_combo_one_slot_filling(dm_session):
    """
    C.4) 套餐一 slot filling
    Given：我要套餐一
    Then：系統會依子品項缺槽逐一追問
    And：最後結帳總價必須等於套餐一固定價 80 元
    """
    dm = dm_session["dm"]
    session_id = dm_session["session_id"]
    
    response = dm.handle(session_id, "我要套餐一")
    # Combo 1: 醬燒肉片蛋餅 + 豆漿(大)
    
    # Drink needs temp.
    if "冰" in response or "溫" in response:
        response = dm.handle(session_id, "冰的")
        
    assert "還需要什麼" in response or "套餐一" in response
    
    response = dm.handle(session_id, "結帳")
    assert "80元" in response

def test_combo_two_plus_snack(dm_session):
    """
    D.5) 套餐與一般品項混點
    Given：我要套餐二再一個薯餅
    Then：最終 cart 內應有 2 個品項（1 個 combo + 1 個 snack）
    And：結帳總價 = 套餐二 70 + 薯餅 20 = 90
    """
    dm = dm_session["dm"]
    session_id = dm_session["session_id"]
    
    response = dm.handle(session_id, "我要套餐二再一個薯餅")
    
    # Combo 2 (Riceball + Drink) + Snack
    
    if "米" in response:
        response = dm.handle(session_id, "白米")
    if "冰" in response or "溫" in response:
        response = dm.handle(session_id, "冰的")
        
    response = dm.handle(session_id, "結帳")
    assert "90元" in response
    # "共 2 個品項"
    assert "2 個品項" in response
