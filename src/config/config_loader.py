import json
from pathlib import Path
from typing import Any, Dict

_CONFIG_CACHE: Dict[str, Any] = {}

def load_json_config(rel_path: str) -> Dict[str, Any]:
    if rel_path in _CONFIG_CACHE:
        return _CONFIG_CACHE[rel_path]

    base = Path(__file__).resolve().parent
    p = base / rel_path
    with open(p, "r", encoding="utf-8-sig") as f:
        data = json.load(f)

    _CONFIG_CACHE[rel_path] = data
    return data