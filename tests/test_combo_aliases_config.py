import pytest
import os
from src.config.alias_loader import load_combo_aliases
from src.tools.menu import menu_price_service

def test_combo_aliases_file_loadable():
    """
    Test that the alias configuration file can be loaded and contains expected keys.
    """
    config = load_combo_aliases()
    assert isinstance(config, dict), "Config should be a dictionary"
    assert "manual_aliases" in config, "Config should contain 'manual_aliases'"
    assert "normalize_rules" in config, "Config should contain 'normalize_rules'"
    assert "allow_single_item_keywords" in config, "Config should contain 'allow_single_item_keywords'"
    
    # Check known aliases exist (basic sanity check)
    assert "薯條" in config["manual_aliases"]
    assert "香酥脆薯" == config["manual_aliases"]["薯條"]

def test_combo_aliases_targets_exist_in_menu():
    """
    Test that all targets in 'manual_aliases' exist in the actual menu.
    This prevents mapping to non-existent SKUs.
    """
    config = load_combo_aliases()
    manual_aliases = config.get("manual_aliases", {})
    
    # Load raw menu to check existence
    menu_items = menu_price_service.get_raw_menu()
    
    # Create a set of (category, name) or just name for easier checking
    # Menu structure: [{"category": "...", "name": "...", "price": ...}, ...]
    valid_names = {item['name'] for item in menu_items if 'name' in item}
    
    for alias, target_name in manual_aliases.items():
        # Target must be either a valid full name OR a base name that exists as a prefix
        exists_as_full = target_name in valid_names
        exists_as_base = any(name.startswith(target_name) for name in valid_names)
        assert exists_as_full or exists_as_base, f"Alias target '{target_name}' for '{alias}' does not exist in menu_all.json"

def test_combo_aliases_whitelist_logic():
    """
    Test that whitelist keywords are effectively strings.
    """
    config = load_combo_aliases()
    whitelist = config.get("allow_single_item_keywords", [])
    assert isinstance(whitelist, list)
    for keyword in whitelist:
        assert isinstance(keyword, str)
