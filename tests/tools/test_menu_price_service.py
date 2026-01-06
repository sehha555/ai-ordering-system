import pytest
from src.tools.menu import menu_price_service

@pytest.fixture(autouse=True)
def clear_menu_cache():
    """Fixture to automatically clear the menu service cache before each test."""
    menu_price_service.clear_cache()
    yield
    menu_price_service.clear_cache()

def test_get_price_success():
    """
    Tests successful price retrieval for a valid item.
    """
    # Act
    price = menu_price_service.get_price("蛋餅", "起司蛋餅")
    
    # Assert
    assert price == 40

def test_get_price_not_found_item():
    """
    Tests that a KeyError is raised for a non-existent item in a valid category.
    """
    # Assert
    with pytest.raises(KeyError) as excinfo:
        menu_price_service.get_price("蛋餅", "不存在的蛋餅")
    
    assert "不存在的蛋餅" in str(excinfo.value)
    assert "蛋餅" in str(excinfo.value)

def test_get_price_not_found_category():
    """
    Tests that a KeyError is raised for a non-existent category.
    """
    # Assert
    with pytest.raises(KeyError) as excinfo:
        menu_price_service.get_price("不存在的類別", "起司蛋餅")
        
    assert "不存在的類別" in str(excinfo.value)

def test_menu_loading_error(monkeypatch):
    """
    Tests that a RuntimeError is raised if the menu file is missing.
    """
    # Arrange
    # Invalidate cache just in case, though fixture should handle it.
    menu_price_service.clear_cache()
    
    # Make the file open operation raise FileNotFoundError
    def mock_open(*args, **kwargs):
        raise FileNotFoundError("File not found for testing")
    
    monkeypatch.setattr("builtins.open", mock_open)
    
    # Act & Assert
    with pytest.raises(RuntimeError) as excinfo:
        menu_price_service.get_price("蛋餅", "起司蛋餅")
        
    assert "Failed to load or parse base menu file" in str(excinfo.value)

def test_get_raw_menu_returns_list_of_dicts_with_keys():
    """
    Tests that get_raw_menu returns a list of item dictionaries with expected keys.
    """
    # Act
    raw_menu = menu_price_service.get_raw_menu()

    # Assert
    assert isinstance(raw_menu, list)
    assert len(raw_menu) > 0
    
    first_item = raw_menu[0]
    assert isinstance(first_item, dict)
    assert "category" in first_item
    assert "name" in first_item
    assert "price" in first_item

def test_get_raw_menu_loading_error(monkeypatch):
    """
    Tests that get_raw_menu also raises a RuntimeError if the menu file is missing.
    """
    # Arrange
    menu_price_service.clear_cache()
    def mock_open(*args, **kwargs):
        raise FileNotFoundError("File not found for testing")
    monkeypatch.setattr("builtins.open", mock_open)
    
    # Act & Assert
    with pytest.raises(RuntimeError) as excinfo:
        menu_price_service.get_raw_menu()
        
    assert "Failed to load or parse base menu file" in str(excinfo.value)
