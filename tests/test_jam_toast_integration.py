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
    return {
        "dm": DialogueManager(),
        "session_id": str(uuid.uuid4()),
    }

def test_order_strawberry_toast_defaults_to_thin(dm_session):
    """測試「我要草莓吐司」=> 果醬吐司(草莓/薄片)，20元"""
    dm = dm_session["dm"]
    session_id = dm_session["session_id"]
    
    response = dm.handle(session_id, "我要草莓吐司")
    assert "好的，1份 果醬吐司(草莓/薄片)，還需要什麼嗎？" in response
    
    response = dm.handle(session_id, "結帳")
    assert "這樣一共" in response
    assert "20元" in response

def test_order_thick_toast_no_toast_customization(dm_session):
    """測試「我要厚片奶酥不烤」=> 果醬吐司(奶酥/厚片)(不烤)，30元"""
    dm = dm_session["dm"]
    session_id = dm_session["session_id"]
    
    response = dm.handle(session_id, "我要厚片奶酥不烤")
    assert "好的，1份 果醬吐司(奶酥/厚片)(不烤)，還需要什麼嗎？" in response
    
    response = dm.handle(session_id, "結帳")
    assert "這樣一共" in response
    assert "30元" in response

def test_order_thin_toast_with_invalid_cut_edge(dm_session):
    """測試「我要花生薄片切邊」=> 錯誤（薄片不可切邊）"""
    dm = dm_session["dm"]
    session_id = dm_session["session_id"]
    
    response = dm.handle(session_id, "我要花生薄片切邊")
    assert "不好意思，只有厚片才能切邊喔！" in response

def test_order_two_thick_toasts_with_cut_edge(dm_session):
    """測試「我要兩份蒜香厚片切邊」=> 果醬吐司(蒜香/厚片)(切邊)x2，60元"""
    dm = dm_session["dm"]
    session_id = dm_session["session_id"]

    response = dm.handle(session_id, "我要兩份蒜香厚片切邊")
    assert "好的，2份 果醬吐司(蒜香/厚片)(切邊)，還需要什麼嗎？" in response

    response = dm.handle(session_id, "結帳")
    assert "這樣一共" in response
    assert "60元" in response

def test_order_chocolate_thin_toast(dm_session):
    """測試「我要巧克力薄片」=> 果醬吐司(巧克力/薄片)，20元"""
    dm = dm_session["dm"]
    session_id = dm_session["session_id"]

    response = dm.handle(session_id, "我要巧克力薄片")
    assert "好的，1份 果醬吐司(巧克力/薄片)，還需要什麼嗎？" in response

    response = dm.handle(session_id, "結帳")
    assert "這樣一共" in response
    assert "20元" in response
