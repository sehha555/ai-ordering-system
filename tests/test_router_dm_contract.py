"""
Tests the contract between DialogueManager and its dependencies,
ensuring that DM only relies on stable, public interfaces.
"""
import inspect
import typing
import pytest
from src.tools import order_router

@pytest.mark.contract
def test_order_router_exposes_route_function():
    """
    Ensures that the order_router module provides a `route` function
    with the expected signature, which the DialogueManager depends on.
    This prevents regressions where the function is renamed or its
    signature changes, which would break the DialogueManager.
    """
    assert hasattr(order_router, 'route'), "order_router module must have a 'route' function."
    
    route_func = getattr(order_router, 'route')
    assert callable(route_func), "'route' must be a callable function."

    # Check the signature using get_type_hints to resolve forward references
    try:
        type_hints = typing.get_type_hints(route_func)
    except (NameError, TypeError) as e:
        pytest.fail(f"Could not resolve type hints for order_router.route: {e}")

    assert 'text' in type_hints
    assert type_hints['text'] is str
    
    assert 'current_order_has_main' in type_hints
    assert type_hints['current_order_has_main'] is bool
    
    # Check the return type hint
    assert 'return' in type_hints
    assert type_hints['return'] == typing.Dict[str, typing.Any]
    
    # Also check default value via inspect, as get_type_hints doesn't provide it
    sig = inspect.signature(route_func)
    assert sig.parameters['current_order_has_main'].default is False

