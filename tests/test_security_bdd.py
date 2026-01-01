"""
BDD tests for security-related scenarios, such as prompt injection.
"""
import uuid
from unittest.mock import Mock
from pytest_bdd import scenarios, given, when, then, parsers
import pytest

from src.dm.dialogue_manager import DialogueManager

pytestmark = pytest.mark.security

scenarios('security_prompt_injection.feature')


# Fixtures
@pytest.fixture
def context():
    """Test context that holds DM instance, session_id, and a mock LLM caller."""
    # We don't initialize the DM here because the mock needs to be created first.
    return {
        "session_id": str(uuid.uuid4()),
        "responses": [],
        "mock_llm": Mock(),
    }


# Given steps
@given('我有一個新的對話 session')
def new_dialogue_session(context):
    mock_llm = context["mock_llm"]
    # Configure the mock to simulate the case where the LLM does not find a valid tool to call.
    # This is the expected behavior for a prompt injection attempt.
    mock_llm.call_tool_required.return_value = {'ok': False}
    
    context["dm"] = DialogueManager(llm=mock_llm)
    pass

@given('系統的 LLM tool-caller 已被監控')
def llm_tool_caller_is_mocked(context):
    # This step just clarifies the test setup. The actual mocking
    # happens in the fixture and session creation.
    assert isinstance(context["dm"].llm, Mock)


# When steps
@when(parsers.parse('我說「{text}」'))
def i_say(context, text):
    """Simulate a user turn."""
    response = context["dm"].handle(context["session_id"], text)
    context["responses"].append(response)


# Then steps
@then('系統應回覆點餐澄清或拒絕')
def bot_should_clarify_or_refuse(context):
    last_response = context["responses"][-1]
    # The default "unknown" response from the DM is "請再說清楚一點～"
    # or a clarification question. We check for these known safe responses.
    known_safe_responses = ["請再說清楚一點～", "想點哪一類？"]
    assert any(safe_text in last_response for safe_text in known_safe_responses)

@then('系統不得回傳內部關鍵字全集或配方全集')
def system_should_not_leak_keywords(context):
    last_response = context["responses"][-1]
    # Check for some representative internal keywords that shouldn't be leaked.
    assert "RICE_KEYWORDS" not in last_response
    assert "FLAVOR_ALIASES" not in last_response
    assert "醬燒里肌" not in last_response # A recipe key
    assert len(last_response) < 200 # A general safety check against large data dumps

@then('系統不得呼叫任何 LLM 工具')
def system_should_not_call_llm_tools(context):
    mock_llm = context["mock_llm"]
    # The DM should route this to "unknown" and try to call the LLM,
    # but our mock will return {'ok': False}, preventing execution.
    assert mock_llm.call_tool_required.call_count == 1
    assert mock_llm.execute_tool_call.call_count == 0
