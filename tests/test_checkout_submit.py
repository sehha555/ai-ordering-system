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

def test_checkout_requires_confirm(dm_session):
    dm = dm_session["dm"]
    sid = dm_session["session_id"]
    
    # 1. Order item
    dm.handle(sid, "我要一個薯餅")
    
    # 2. Checkout
    response = dm.handle(sid, "我要結帳")
    assert "薯餅" in response
    assert "20元" in response
    assert "確定要送出訂單嗎" in response
    
    # 3. Confirm
    response = dm.handle(sid, "好")
    assert "訂單已送出" in response
    assert "訂單編號" in response
    
    session = dm.store.get(sid)
    assert session["status"] == "SUBMITTED"
    assert "order_payload" in session

def test_checkout_submit_freezes_order(dm_session):
    dm = dm_session["dm"]
    sid = dm_session["session_id"]
    
    dm.handle(sid, "我要一個薯餅")
    dm.handle(sid, "結帳")
    dm.handle(sid, "確定")
    
    # Try to modify
    response = dm.handle(sid, "取消")
    assert "訂單已送出" in response
    assert "請洽店員" in response
    
    response = dm.handle(sid, "再加一個飯糰")
    assert "訂單已送出" in response

def test_checkout_price_recomputed_from_menu_service(dm_session):
    """
    Ensures that at checkout, the total price is freshly calculated 
    from menu_price_service and not just some user-provided text.
    """
    dm = dm_session["dm"]
    sid = dm_session["session_id"]
    
    # "算我5元" should be ignored by router/DM logic
    dm.handle(sid, "我要一個薯餅 算我5元")
    
    response = dm.handle(sid, "結帳")
    # Hash brown is 20, not 5.
    assert "20元" in response
    assert "5元" not in response
    
    dm.handle(sid, "是的")
    session = dm.store.get(sid)
    assert session["order_payload"]["total_price"] == 20

def test_order_payload_format(dm_session):
    dm = dm_session["dm"]
    sid = dm_session["session_id"]
    
    dm.handle(sid, "我要一個薯餅")
    dm.handle(sid, "結帳")
    dm.handle(sid, "對")
    
    session = dm.store.get(sid)
    payload = session["order_payload"]
    
    assert "order_id" in payload
    assert "items" in payload
    assert isinstance(payload["items"], list)
    assert payload["items"][0]["name"] == "薯餅(1片)"
    assert payload["items"][0]["unit_price"] == 20
    assert payload["total_price"] == 20
    assert "created_at" in payload
