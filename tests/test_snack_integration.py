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

def test_order_one_hash_brown_success(dm_session):
    """測試「我要一份薯餅」=> 結帳 20"""
    dm = dm_session["dm"]
    session_id = dm_session["session_id"]

    response = dm.handle(session_id, "我要一份薯餅")
    assert "好的，1份 薯餅(1片)，還需要什麼嗎？" in response

    response = dm.handle(session_id, "結帳")
    assert "這樣一共" in response
    assert "20元" in response

def test_order_two_chicken_nuggets_success(dm_session):
    """測試「我要兩份雞塊」=> 結帳 80"""
    dm = dm_session["dm"]
    session_id = dm_session["session_id"]

    response = dm.handle(session_id, "我要兩份雞塊")
    assert "好的，2份 麥克雞塊(5個)，還需要什麼嗎？" in response

    response = dm.handle(session_id, "結帳")
    assert "這樣一共" in response
    assert "80元" in response

def test_order_hash_brown_egg_toast_routes_to_carrier(dm_session):
    """測試「我要薯餅蛋吐司」=> 必須走 carrier，不可走 snack"""
    dm = dm_session["dm"]
    session_id = dm_session["session_id"]

    response = dm.handle(session_id, "我要薯餅蛋吐司")
    assert "好的，1份 薯餅蛋吐司，還需要什麼嗎？" in response

    response = dm.handle(session_id, "結帳")
    assert "這樣一共" in response
    assert "45元" in response

def test_order_meat_slice_alias_success(dm_session):
    """測試「我要肉片」=> 醬燒肉片(1份)，結帳 35"""
    dm = dm_session["dm"]
    session_id = dm_session["session_id"]

    response = dm.handle(session_id, "我要肉片")
    assert "好的，1份 醬燒肉片(1份)，還需要什麼嗎？" in response

    response = dm.handle(session_id, "結帳")
    assert "這樣一共" in response
    assert "35元" in response

def test_order_nuggets_no_pepper_success(dm_session):
    """測試「我要雞塊不要胡椒」=> 麥克雞塊(5個)，結帳 40 + 提示無椒"""
    dm = dm_session["dm"]
    session_id = dm_session["session_id"]

    response = dm.handle(session_id, "我要雞塊不要胡椒")
    assert "好的，1份 麥克雞塊(5個)(不要胡椒)，還需要什麼嗎？" in response

    response = dm.handle(session_id, "結帳")
    assert "這樣一共" in response
    assert "40元" in response
    assert "(不要胡椒)" in response

def test_order_half_cooked_egg_success(dm_session):
    """測試「我要半熟蛋」=> 荷包蛋，egg_cook="半熟" """
    dm = dm_session["dm"]
    session_id = dm_session["session_id"]

    response = dm.handle(session_id, "我要半熟蛋")
    assert "好的，1份 荷包蛋(半熟)，還需要什麼嗎？" in response
    
    # 驗證內部狀態
    cart = dm.store.get(session_id)["cart"]
    assert len(cart) == 1
    assert cart[0]["itemtype"] == "snack"
    assert cart[0]["snack"] == "荷包蛋"
    assert cart[0]["egg_cook"] == "半熟"

    response = dm.handle(session_id, "結帳")
    assert "這樣一共" in response
    assert "15元" in response