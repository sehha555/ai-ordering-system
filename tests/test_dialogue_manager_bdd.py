"""
BDD tests for the Dialogue Manager's end-to-end flows.
"""
import uuid
import re
from pytest_bdd import scenarios, given, when, then, parsers
import pytest

from src.dm.dialogue_manager import DialogueManager
from src.tools.riceball_tool import menu_tool

pytestmark = pytest.mark.bdd

scenarios(
    'dm_riceball_checkout_flow.feature',
    'dm_queue_multi_items.feature'
)


# Fixtures
@pytest.fixture
def context():
    """Test context that holds DM instance, session_id, and responses."""
    return {
        "dm": DialogueManager(),
        "session_id": str(uuid.uuid4()),
        "responses": [],
    }


# Given steps
@given('我有一個新的對話 session')
def new_dialogue_session(context):
    # This is handled by the fixture setup
    pass

@given('我尚未加入任何品項')
def no_items_in_cart(context):
    # The session is new, so the cart is empty by default.
    state = context["dm"].store.get(context["session_id"])
    assert state is None or not state.get("cart")


# When steps
@when(parsers.parse('我說「{text}」'))
def i_say(context, text):
    """Simulate a user turn."""
    response = context["dm"].handle(context["session_id"], text)
    context["responses"].append(response)


# Then steps
@then(parsers.parse('機器人應回覆「{text}」'))
def bot_should_reply(context, text):
    last_response = context["responses"][-1]
    assert text in last_response

@then(parsers.parse('機器人回覆不應詢問米種或口味'))
def bot_should_not_ask_rice_or_flavor(context):
    last_response = context["responses"][-1]
    assert "米種" not in last_response
    assert "口味" not in last_response

@then(parsers.parse('機器人應詢問米種'))
def bot_should_ask_for_rice(context):
    last_response = context["responses"][-1]
    assert "米" in last_response

@then(parsers.parse('機器人應提醒尚缺米種'))
def bot_should_warn_missing_rice(context):
    last_response = context["responses"][-1]
    assert "還差米種" in last_response

@then(parsers.parse('回應中不應包含「{text}」'))
def response_should_not_contain(context, text):
    last_response = context["responses"][-1]
    assert text not in last_response

@then('機器人應回覆確認已加入醬燒里肌白米和泡菜白米')
def bot_should_confirm_both_items(context):
    last_response = context["responses"][-1]
    assert "醬燒里肌白米" in last_response
    assert "泡菜白米" in last_response
    assert "已加入" in last_response

@then(parsers.parse('機器人應詢問是否還需要什麼'))
def bot_should_ask_for_more(context):
    last_response = context["responses"][-1]
    assert "還需要什麼嗎？" in last_response

# --- Price Verification Steps ---

def _get_price_from_response(response: str) -> int | None:
    match = re.search(r'(\d+)\s*元', response)
    if match:
        return int(match.group(1))
    return None

@then('結帳金額應為泡菜飯糰的正確價格')
def checkout_price_should_be_correct_for_kimchi(context):
    expected_price = menu_tool.quote_riceball_price(flavor="韓式泡菜", large=False, heavy=False, extra_egg=False).get("total_price")
    last_response = context["responses"][-1]
    actual_price = _get_price_from_response(last_response)
    assert actual_price is not None
    assert actual_price == expected_price

@then('結帳金額應為醬燒里肌紫米飯糰的正確價格')
def checkout_price_should_be_correct_for_pork(context):
    # The DM calculates the price based on the frame, which for this flow,
    # will not have `heavy=True`. So we expect the base price from the menu.
    expected_price = menu_tool.quote_riceball_price(
        flavor="醬燒里肌",
        large=False,
        heavy=False,
        extra_egg=False
    ).get("total_price")

    last_response = context["responses"][-1]
    actual_price = _get_price_from_response(last_response)
    
    assert actual_price is not None, "Could not find price in response"
    assert actual_price == expected_price, f"Price mismatch: expected {expected_price}, got {actual_price}"


import builtins
from src.tools.menu import menu_price_service

def test_egg_pancake_menu_load_error_handling(monkeypatch):
    """
    Given the egg pancake menu file is missing,
    When a user tries to order an egg pancake,
    Then the system should return a user-friendly error message.
    """
    # Arrange
    dm = DialogueManager()
    session_id = "test_session_menu_error"

    # Invalidate the cache in the new central service to force a re-read
    menu_price_service.clear_cache()

    # Mock builtins.open to only fail for the menu file
    original_open = builtins.open
    def mock_open_fail(file, *args, **kwargs):
        # The path to the menu file is constructed via os.path.join,
        # so we check for the filename's presence in the path.
        if isinstance(file, str) and 'menu_all.json' in file:
            raise FileNotFoundError("Mock file not found for testing")
        return original_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", mock_open_fail)

    # Act
    response = dm.handle(session_id, "我要一個蛋餅")

    # Assert
    assert "菜單" in response
    assert "讀取失敗" in response
    assert "蛋餅菜單讀取失敗，請洽服務人員。" in response
    assert "找不到品項" not in response

