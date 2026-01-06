import json
import os
from typing import Dict, Optional, List, Any

# Module-level caches
_raw_menu_cache: Optional[List[Dict[str, Any]]] = None
_price_index_cache: Optional[Dict[str, Dict[str, int]]] = None

def _load_menu_if_needed():
    """
    Loads menu data from menu_all.json if not already cached.
    Populates both the raw menu cache and the processed price index cache.
    Raises RuntimeError on file loading/parsing errors.
    """
    global _raw_menu_cache, _price_index_cache
    if _price_index_cache is not None:
        return

    current_dir = os.path.dirname(os.path.abspath(__file__))
    json_path = os.path.join(current_dir, 'menu_all.json')

    try:
        with open(json_path, 'r', encoding='utf-8-sig') as f:
            menu_data: List[Dict[str, Any]] = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        raise RuntimeError(f"Failed to load or parse base menu file at {json_path}") from e

    _raw_menu_cache = menu_data

    processed_index: Dict[str, Dict[str, int]] = {}
    if isinstance(menu_data, list):
        for item in menu_data:
            category = item.get("category")
            name = item.get("name")
            price = item.get("price")
            if category and name and isinstance(price, int):
                if category not in processed_index:
                    processed_index[category] = {}
                processed_index[category][name] = price
    
    _price_index_cache = processed_index

def get_price(category: str, name: str) -> int:
    """
    Retrieves the price for a given item from the menu.
    """
    _load_menu_if_needed()
    # Non-null assertion is safe because _load_menu_if_needed populates it.
    price_index = _price_index_cache
    
    if category not in price_index:
        raise KeyError(f"Price not found: Category '{category}' does not exist in the menu.")
    
    category_items = price_index[category]
    
    if name not in category_items:
        raise KeyError(f"Price not found: Item '{name}' not found in category '{category}'.")
        
    return category_items[name]

def get_raw_menu() -> List[Dict[str, Any]]:
    """
    Returns the raw menu data as a list of item dictionaries.
    """
    _load_menu_if_needed()
    # Non-null assertion is safe because _load_menu_if_needed populates it.
    return _raw_menu_cache

def clear_cache():
    """Clears the module-level cache. Useful for testing."""
    global _raw_menu_cache, _price_index_cache
    _raw_menu_cache = None
    _price_index_cache = None
