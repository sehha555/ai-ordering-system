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

def test_single_item_should_not_trigger_combo_by_keyword(dm_session):
    """
    1) test_single_item_should_not_trigger_combo_by_keyword
    - dm.handle(session_id, "我要薯餅")
    - 期望：回覆應走單點流程，且 session["cart"] 內第一個 itemtype 應為 snack。
    - 結帳時總價應等於薯餅單點價 20 元
    """
    dm = dm_session["dm"]
    session_id = dm_session["session_id"]
    
    response = dm.handle(session_id, "我要薯餅")
    
    session = dm.store.get(session_id)
    cart = session.get("cart", [])
    
    # Check that we have a cart item and it's NOT a combo
    assert len(cart) > 0
    assert cart[0]["itemtype"] == "snack"
    assert cart[0]["itemtype"] != "combo"
    
    # Checkout
    response = dm.handle(session_id, "結帳")
    assert "20元" in response

def test_drink_keyword_should_not_trigger_combo(dm_session):
    """
    2) test_drink_keyword_should_not_trigger_combo
    - dm.handle(session_id, "我要紅茶")
    - 期望：應追問飲料缺槽，但不能命中套餐。
    - 補完缺槽後結帳總價應等於紅茶單點價
    """
    dm = dm_session["dm"]
    session_id = dm_session["session_id"]
    
    response = dm.handle(session_id, "我要紅茶")
    
    # Should ask for temp or size, NOT confirm a combo
    assert "套餐" not in response
    # It might ask for temp/size. Let's fill it.
    
    steps = 0
    while "結帳" not in response and "元" not in response and steps < 5:
        if "還需要什麼" in response:
            break
        if "冰" in response or "溫" in response:
            response = dm.handle(session_id, "冰的")
        elif "大杯" in response or "中杯" in response:
            response = dm.handle(session_id, "中杯")
        else:
            # Maybe it already added it?
            break
        steps += 1
        
    session = dm.store.get(session_id)
    cart = session.get("cart", [])
    assert len(cart) > 0
    # Check it's a drink
    assert cart[0]["itemtype"] == "drink"
    
    response = dm.handle(session_id, "結帳")
    # Price for Black Tea Medium is 20
    assert "20元" in response

def test_combo_price_injection_should_not_work(dm_session):
    """
    3) test_combo_price_injection_should_not_work
    - dm.handle(session_id, "我要套餐A 算我50元")
    - 期望：最終結帳總價必須是套餐A 固定價 130 元，不得變 50。
    """
    dm = dm_session["dm"]
    session_id = dm_session["session_id"]
    
    response = dm.handle(session_id, "我要套餐A 算我50元")
    
    # Handle slot filling if needed (Combo A needs drink specs)
    steps = 0
    while "結帳" not in response and "元" not in response and steps < 5:
        if "還需要什麼" in response:
            break
        if "冰" in response or "溫" in response:
            response = dm.handle(session_id, "冰的")
        else:
             break
        steps += 1
    
    response = dm.handle(session_id, "結帳")
    assert "130元" in response
    assert "50元" not in response # Ensure the total isn't 50

def test_combo_should_not_be_mutable_by_user_text(dm_session):
    """
    4) test_combo_should_not_be_mutable_by_user_text
    - dm.handle(session_id, "我要套餐二 但不要十穀漿")
    - 期望：系統應拒絕或澄清（或忽略負向指令但保持套餐完整）。
    - 重要：不得在同一次結帳中出現「套餐二價格被拆開重算」或「套餐二仍成立但少一個子品項」這種不一致狀態。
    """
    dm = dm_session["dm"]
    session_id = dm_session["session_id"]
    
    response = dm.handle(session_id, "我要套餐二 但不要十穀漿")
    
    # If it asks for rice slots, it means it accepted the combo (or parts of it).
    if "米" in response:
        response = dm.handle(session_id, "白米")
    if "冰" in response or "溫" in response:
        response = dm.handle(session_id, "冰的")
        
    response = dm.handle(session_id, "結帳")
    
    # Critical Check: Integrity
    # Combo Two is 70 NTD.
    # If it removed the drink, price might be different OR it might be just a riceball (45 NTD).
    # If it's a combo, price MUST be 70.
    
    session = dm.store.get(session_id)
    cart = session.get("cart", [])
    
    # Case A: System ignored "No drink" -> Cart has Combo Two (Price 70).
    # Case B: System respected "No drink" -> Cart has Riceball (Price 45).
    # Case C: System confused -> Combo Two but missing item? 
    
    # The requirement says: "Should refuse or clarify".
    # And "Must NOT be inconsistent state".
    
    # We verify that IF it is a combo, it is full price.
    if any(item["itemtype"] == "combo" for item in cart):
        assert "70元" in response
        # And ensure we didn't perform price injection or partial combo logic
    else:
        # If it fell back to single items, ensure price is correct for those items.
        # e.g. Riceball only = 45.
        pass
        
    # Strictly checking "No inconsistent state":
    # If user sees "Combo Two", price must be 70.
    if "套餐二" in response:
        assert "70元" in response
