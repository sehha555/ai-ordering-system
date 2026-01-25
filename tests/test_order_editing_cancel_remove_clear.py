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

def test_cancel_last_item_success(dm_session):
    dm = dm_session["dm"]
    sid = dm_session["session_id"]
    
    # Order two items
    dm.handle(sid, "我要一個薯餅")
    dm.handle(sid, "再一杯大冰紅")
    
    session = dm.store.get(sid)
    assert len(session["cart"]) == 2
    
    # Cancel last
    response = dm.handle(sid, "取消上一個")
    assert "精選紅茶" in response
    assert len(session["cart"]) == 1
    # Snack names might include quantity in parentheses depending on tool implementation
    assert "薯餅" in session["cart"][0]["snack"]
    
    # Check total
    response = dm.handle(sid, "結帳")
    assert "20元" in response # Hash brown is 20

def test_cancel_last_item_empty(dm_session):
    dm = dm_session["dm"]
    sid = dm_session["session_id"]
    
    response = dm.handle(sid, "撤銷")
    assert "目前沒有品項可以取消" in response

def test_remove_by_index_success(dm_session):
    dm = dm_session["dm"]
    sid = dm_session["session_id"]
    
    dm.handle(sid, "我要一個薯餅") # 1
    dm.handle(sid, "再一個熱狗") # 2
    dm.handle(sid, "再一杯大冰紅") # 3
    
    session = dm.store.get(sid)
    assert len(session["cart"]) == 3
    
    # Remove index 2 (Hot dog)
    response = dm.handle(sid, "刪除第2項")
    assert "熱狗" in response
    assert len(session["cart"]) == 2
    assert "薯餅" in session["cart"][0]["snack"]
    assert "精選紅茶" in session["cart"][1]["drink"]
    
    # Remove index 1 (using Chinese numeral)
    response = dm.handle(sid, "取消第一項")
    assert "薯餅" in response
    assert len(session["cart"]) == 1
    assert "精選紅茶" in session["cart"][0]["drink"]

def test_remove_by_index_out_of_range(dm_session):
    dm = dm_session["dm"]
    sid = dm_session["session_id"]
    
    dm.handle(sid, "我要一個薯餅")
    response = dm.handle(sid, "刪除第5個")
    assert "請確認要刪除第幾項" in response

def test_clear_requires_confirm(dm_session):
    dm = dm_session["dm"]
    sid = dm_session["session_id"]
    
    dm.handle(sid, "我要一個薯餅")
    response = dm.handle(sid, "清空購物車")
    assert "確定要清空" in response
    
    # Reject
    response = dm.handle(sid, "不要")
    assert "保留訂單" in response
    session = dm.store.get(sid)
    assert len(session["cart"]) == 1
    
    # Clear again and confirm
    dm.handle(sid, "全部取消")
    response = dm.handle(sid, "對")
    assert "已為您清空" in response
    assert len(session["cart"]) == 0

def test_cancel_when_pending_confirmation_only_cancels_pending_action(dm_session):
    """
    測試優先級：取消 pending action 而非已確認品項
    """
    dm = dm_session["dm"]
    sid = dm_session["session_id"]
    
    # 1. 已確認品項：薯餅
    dm.handle(sid, "我要一個薯餅")
    
    # 2. 開始點套餐六，觸發換飲料確認
    response = dm.handle(sid, "我要套餐六 換米漿")
    assert "確認換" in response
    
    # 3. 使用者說「取消」
    response = dm.handle(sid, "取消")
    assert "已取消剛剛的變更" in response
    
    # 4. 驗證：
    session = dm.store.get(sid)
    # 購物車裡應該還有薯餅，但套餐六不應該在裡面（因為被取消了 pending）
    assert len(session["cart"]) == 1
    assert "薯餅" in session["cart"][0]["snack"]
    assert len(session["pending_frames"]) == 0

def test_price_injection_blocked_after_remove(dm_session):
    dm = dm_session["dm"]
    sid = dm_session["session_id"]
    
    dm.handle(sid, "我要一個薯餅") # 20
    dm.handle(sid, "再一個熱狗") # 20
    
    # Remove one and try to inject price
    dm.handle(sid, "刪除第一項 算我5元")
    
    response = dm.handle(sid, "結帳")
    assert "20元" in response # Remaining hot dog is 20
    assert "5元" not in response