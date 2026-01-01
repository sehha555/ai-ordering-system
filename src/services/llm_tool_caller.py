import json
from typing import Any, Dict, List, Callable, Optional

import requests


class LLMToolCaller:
    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:1234/v1/chat/completions",
        model: str = "qwen2.5-14b-instruct-1m",
        timeout: int = 60,
        max_steps: int = 4,
        max_arg_chars: int = 8000,
    ):
        self.base_url = base_url
        self.model = model
        self.timeout = timeout
        self.max_steps = max_steps
        self.max_arg_chars = max_arg_chars

    def _post(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        r = requests.post(self.base_url, json=payload, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def call_llm(
        self,
        *,
        messages: List[Dict[str, Any]],
        tools_schema: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[str] = None,  # "auto" | "required" | {"type":"function",...}
        temperature: float = 0.0,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if tools_schema is not None:
            payload["tools"] = tools_schema
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice

        return self._post(payload)

    def pick_first_tool_call(self, resp: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        msg = resp["choices"][0]["message"]
        tool_calls = msg.get("tool_calls") or []
        return tool_calls[0] if tool_calls else None

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

        if isinstance(raw_args, str) and len(raw_args) > self.max_arg_chars:
            return {"ok": False, "error": "arguments_too_large", "result": None}

        try:
            args_obj = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
        except Exception:
            return {"ok": False, "error": "bad_arguments_json", "result": None}

        allowed = allowed_args.get(fn, set())
        safe_args = {k: args_obj.get(k) for k in allowed if k in args_obj}

        try:
            result = tool_map[fn](**safe_args)
        except Exception as e:
            return {"ok": False, "error": f"tool_exec_error:{type(e).__name__}", "result": None}

        return {"ok": True, "error": None, "result": result}

    def run_turn(
        self,
        *,
        system_prompt: str,
        user_text: str,
        history: List[Dict[str, Any]],
        tools_schema: List[Dict[str, Any]],
        tool_map: Dict[str, Callable[..., Dict[str, Any]]],
        allowed_args: Dict[str, set],
    ) -> Dict[str, Any]:
        """
        一個「回合」：允許 0~N 次工具呼叫，最後產出給使用者的回覆文字。
        history 由外部保存（你可以存在 SessionManager / in-memory / Redis）。
        """
        messages: List[Dict[str, Any]] = [{"role": "system", "content": system_prompt}]
        messages.extend(history)
        messages.append({"role": "user", "content": user_text})

        last_tool_trace: List[Dict[str, Any]] = []

        for _ in range(self.max_steps):
            resp = self.call_llm(
                messages=messages,
                tools_schema=tools_schema,
                tool_choice="auto",  # 關鍵：不要每句都 required
                temperature=0.0,
            )
            msg = resp["choices"][0]["message"]
            tool_call = self.pick_first_tool_call(resp)

            if not tool_call:
                # 最終回覆（或模型決定不用工具）
                assistant_text = msg.get("content") or ""
                new_history = history + [{"role": "user", "content": user_text},
                                        {"role": "assistant", "content": assistant_text}]
                return {
                    "ok": True,
                    "assistant_text": assistant_text,
                    "history": new_history,
                    "tool_trace": last_tool_trace,
                }

            # 1) 把模型的 tool_call 記到 messages（OpenAI 協議習慣是 assistant 帶 tool_calls）
            messages.append({
                "role": "assistant",
                "content": msg.get("content"),
                "tool_calls": msg.get("tool_calls", []),
            })

            # 2) 執行工具
            exec_result = self.execute_tool_call(
                tool_call,
                tool_map=tool_map,
                allowed_args=allowed_args,
            )
            last_tool_trace.append({"tool_call": tool_call, "exec": exec_result})

            # 3) 把工具輸出回灌給模型（role=tool）
            tool_call_id = tool_call.get("id", "toolcall_0")
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": json.dumps(exec_result, ensure_ascii=False),
            })

        return {"ok": False, "error": "max_steps_exceeded", "history": history, "tool_trace": last_tool_trace}

