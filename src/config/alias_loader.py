import json
import os
from typing import Any, Dict
from loguru import logger

def load_combo_aliases(file_path: str = None) -> Dict[str, Any]:
    """
    Loads combo aliases configuration from a JSON file.
    Default path is 'src/config/combo_aliases.json'.
    Returns a dictionary with configuration or empty dict if file not found.
    """
    if file_path is None:
        # Determine absolute path relative to this file
        current_dir = os.path.dirname(os.path.abspath(__file__))
        file_path = os.path.join(current_dir, "combo_aliases.json")

    try:
        with open(file_path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.warning("Alias config file not found at {}", file_path)
        return {}
    except json.JSONDecodeError as e:
        logger.error("Error decoding alias config file: {}", e)
        return {}
