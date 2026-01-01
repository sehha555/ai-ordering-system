"""
This module contains tests for the order_router.py.
"""
from pytest_bdd import scenarios, given, when, then, parsers
import pytest
from src.tools.order_router import route

pytestmark = pytest.mark.bdd

scenarios('router_riceball_normalize.feature',
          'router_rice_keyword_context.feature',
          'router_riceball_from_rice_signal.feature',
          'router_guard_exclude_rice_signal.feature')

# Fixtures
@pytest.fixture
def context():
    return {}

# Given steps
@given('系統已載入飯糰關鍵字')
def system_has_loaded_riceball_keywords():
    # This is assumed to be true as they are loaded on module import
    pass

@given('current_order_has_main 為 true')
def current_order_has_main(context):
    context['current_order_has_main'] = True

@given('系統已載入米種關鍵字')
def system_has_loaded_rice_keywords():
    # This is assumed to be true as they are hardcoded in order_router.py
    pass

@given('Router 已載入各品類關鍵字與米種關鍵字')
def system_has_loaded_all_keywords():
    # This is assumed to be true as they are loaded on module import
    pass

# When steps
@when(parsers.parse('使用者說「{text}」'))
def user_says(context, text):
    current_order_has_main = context.get('current_order_has_main', False)
    context['result'] = route(text, current_order_has_main=current_order_has_main)

# Then steps
@then(parsers.parse('Router 的 route_type 應為 "{expected_route_type}"'))
def router_route_type_should_be(context, expected_route_type):
    assert context['result']['route_type'] == expected_route_type

@then(parsers.parse('needs_clarify 應為 {expected_needs_clarify}'))
def needs_clarify_should_be(context, expected_needs_clarify):
    # Convert string 'true'/'false' to boolean
    expected = expected_needs_clarify.lower() == 'true'
    assert context['result']['needs_clarify'] == expected

@then(parsers.parse('note 應包含 "{expected_note}"'))
def note_should_contain(context, expected_note):
    assert expected_note in context['result']['note']
