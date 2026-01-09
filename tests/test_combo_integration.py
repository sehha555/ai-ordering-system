import pytest
import uuid
from src.dm.dialogue_manager import DialogueManager
from src.tools.menu import menu_price_service

# Fixtures from existing test files
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

def test_order_combo_two_success(dm_session):
    """
    Test ordering "套餐二" which contains "鮪魚飯糰" and "中杯豆漿",
    and verifying the slot filling process and final price.
    Combo Two: 鮪魚飯糰 (needs rice), 中杯豆漿 (needs temp). Price 70.
    """
    dm = dm_session["dm"]
    session_id = dm_session["session_id"]

    # 1. Order Combo Two
    response = dm.handle(session_id, "我要套餐二")
    # Expect clarification for rice of 鮪魚飯糰 (first sub-item)
    assert "還差米種，你要紫米、白米還是混米？" in response

    # 2. Provide rice for 鮪魚飯糰
    response = dm.handle(session_id, "白米")
    # Expect clarification for temp of 中杯豆漿 (second sub-item)
    assert "你要冰的、溫的？" in response

    # 3. Provide temp for 中杯豆漿
    response = dm.handle(session_id, "冰的")
    # Expect confirmation for the entire combo
    assert "好的，1份 套餐二，還需要什麼嗎？" in response

    # 4. Checkout
    response = dm.handle(session_id, "結帳")
    assert "這樣一共" in response
    assert "共 1 個品項" in response
    assert "70元" in response
