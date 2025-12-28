from typing import Dict, Any, Optional

class InMemorySessionStore:
    def __init__(self):
        self._data: Dict[str, Dict[str, Any]] = {}

    def get(self, session_id: str) -> Dict[str, Any]:
        return self._data.setdefault(session_id, {})

    def set(self, session_id: str, state: Dict[str, Any]) -> None:
        self._data[session_id] = state

    def clear(self, session_id: str) -> None:
        self._data.pop(session_id, None)
