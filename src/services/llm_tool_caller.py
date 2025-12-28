import json
from typing import Any, Dict, List, Optional, Callable

import requests

class LLMToolCaller:
    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:1234/v1/chat/completions",
        model: str = "qwen2.5-14b-instruct-1m",
        timeout: int = 60,
    ):
        self.base_url = base_url
        self.model = model
        self.timeout = timeout

    def call_tool_required(self, user_text: str, tools_schema: List[Dict[str, Any]]) -> Dict[str, Any]:
        resp = requests.post(
            self.base_url,
            json={
                "model": self.model,
                "messages": [{"role": "user", "content": user_text}],
                "tools": tools_schema,
                "tool_choice": "required",
                "temperature": 0.0,
            },
            timeout=self.timeout,
        ).json()

        tool_calls = resp["choices"][0]["message"].get("tool_calls", [])
        if not tool_calls:
            return {"ok": False, "error": "no_tool_call", "tool_call": None}
        return {"ok": True, "tool_call": tool_calls[0]}

    def execute_tool_call(
        self,
        tool_call: Dict[str, Any],
        *,
        tool_map: Dict[str, Callable[..., Dict[str, Any]]],
        allowed_args: Dict[str, set],
    ) -> Dict[str, Any]:
        fn = tool_call.get("function", {}).get("name")
        raw_args = tool_call.get("function", {}).get("arguments", "{}")

        if fn not in tool_map:
            return {"ok": False, "error": f"tool_not_allowed:{fn}", "result": None}

        try:
            args_obj = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
        except Exception:
            return {"ok": False, "error": "bad_arguments_json", "result": None}

        # 白名單欄位過濾（防止模型塞多餘欄位/巨大 payload）
        allowed = allowed_args.get(fn, set())
        safe_args = {k: args_obj.get(k) for k in allowed if k in args_obj}

        try:
            result = tool_map[fn](**safe_args)
        except Exception as e:
            return {"ok": False, "error": f"tool_exec_error:{type(e).__name__}", "result": None}

        return {"ok": True, "error": None, "result": result}
