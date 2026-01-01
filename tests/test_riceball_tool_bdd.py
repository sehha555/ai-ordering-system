"""
BDD tests for the riceball_tool's utterance parsing.
"""
from pytest_bdd import scenarios, given, when, then, parsers
import pytest
from src.tools.riceball_tool import menu_tool

pytestmark = pytest.mark.bdd

scenarios(
    'riceball_flavor_kimchi.feature',
    'riceball_protein_ambiguity.feature',
    'riceball_tool_negative_cases.feature',
    'riceball_tool_fallback_strictness.feature'
)

# Fixtures
@pytest.fixture
def context():
    """Test context"""
    return {}

# Given steps
@given('系統已載入飯糰配方與口味別名')
@given('系統已載入飯糰配方與口味提示')
@given('系統已載入飯糰配方與米種關鍵字')
@given('系統已載入飯糰配方')
@given('系統已載入 riceball_recipes 的所有 keys') # New
def system_has_loaded_riceball_data():
    # Assumed to be loaded on menu_tool import
    assert menu_tool.recipes_data is not None
    pass

@given('系統存在包含 "蛋餅" 字樣的飯糰口味 key')
def system_has_egg_pancake_riceball_key(context):
    egg_pancake_key = None
    for key in menu_tool.recipes_data.keys():
        if "蛋餅" in key:
            egg_pancake_key = key
            break
    if egg_pancake_key is None:
        pytest.skip(f"riceball_recipes.json does not contain any key with '蛋餅'. Skipping scenario.")
    context['egg_pancake_key'] = egg_pancake_key

@given('recipes 中存在口味 key「醬燒里肌」')
def system_has_jiangshao_liji_key():
    assert "醬燒里肌" in menu_tool.recipes_data.keys()


# When steps
@when(parsers.parse('使用者說「{text}」'))
def user_says(context, text):
    """Parse the user's utterance and store the result in the context."""
    context['frame'] = menu_tool.parse_riceball_utterance(text)

# Then steps
@then(parsers.parse('parse_riceball_utterance 應回傳 frame 且 flavor 為 "{expected_flavor}"'))
def frame_flavor_should_be(context, expected_flavor):
    assert context['frame']['flavor'] == expected_flavor

@then(parsers.parse('parse_riceball_utterance 的 frame flavor 應為 None'))
def frame_flavor_should_be_none(context):
    assert context['frame']['flavor'] is None

@then(parsers.parse('frame 的 rice 為 "{expected_rice}"'))
def frame_rice_should_be(context, expected_rice):
    assert context['frame']['rice'] == expected_rice

@then(parsers.parse('missing_slots 不應包含 "{slot_name}"'))
def missing_slots_should_not_contain(context, slot_name):
    assert slot_name not in context['frame']['missing_slots']

@then(parsers.parse('frame 的 missing_slots 應包含 "{slot_name}"'))
@then(parsers.parse('missing_slots 應包含 "{slot_name}"'))
def missing_slots_should_contain(context, slot_name):
    assert slot_name in context['frame']['missing_slots']

@then('系統的澄清問句應詢問白米/紫米/混米')
def clarification_should_ask_for_rice(context):
    # The tool's responsibility is to report 'rice' as a missing slot.
    # The Dialogue Manager is responsible for generating the actual question.
    # This step verifies the condition that would trigger such a question.
    assert 'rice' in context['frame']['missing_slots']
