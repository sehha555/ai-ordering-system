from typing import Dict, Any, Optional

class InMemorySessionStore:
    def __init__(self):
        self._data: Dict[str, Dict[str, Any]] = {}

    def get(self, session_id: str, default: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if session_id in self._data:
            return self._data[session_id]
        
        if default is not None:
            return default
        
        # If session_id not in _data and no default is provided, create and return the predefined default session state
        default_session_state = {
            "cart": [],
            "pending_frames": [],
            "last_user_text": None,
            "order": [],
            "current_item": None,
            "missing_slots": [],
            "route_type": None,
            "state": "idle",
        }
        self._data[session_id] = default_session_state
        return default_session_state

    def set(self, session_id: str, state: Dict[str, Any]) -> None:
        self._data[session_id] = state

    def clear(self, session_id: str) -> None:
        self._data.pop(session_id, None)
