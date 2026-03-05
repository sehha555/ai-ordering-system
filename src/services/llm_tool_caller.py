import asyncio
import json
import re
import time
from typing import Any, AsyncIterator, Dict, List, Callable, Optional

import requests
import httpx

from loguru import logger
from src.config.logging_config import PerfTimer
from src.dm.tool_priming import get_priming_messages

_PRIMING_MESSAGES = get_priming_messages()
_NO_THINK_PREFIX = "/no_think\n"  # 關閉 Qwen3 thinking mode，降低延遲

# 允許 early TTS 播報的工具（tool call 成功後立即送語音，降低 TTFA）
_EARLY_TTS_TOOLS = {"add_to_cart", "remove_from_cart"}

from src.utils import SENTENCE_PUNCTS as _SENTENCE_PUNCTS

# Qwen 模型有時把 tool call 輸出到 content 而非 tool_calls 欄位
_TOOL_CALL_RE = re.compile(
    r'[<\|im_start\|>]*\s*'           # 可選的 <|im_start|> 前綴
    r'(?:<tool_call>\s*)?'             # 可選的 <tool_call> 標籤
    r'(\{["\s]*"?name"?\s*:.*?\})'     # JSON body
    r'\s*(?:</tool_call>)?',           # 可選的 </tool_call> 標籤
    re.DOTALL,
)


class LLMToolCaller:
    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:1234/v1/chat/completions",
        model: str = "qwen/qwen3-30b-a3b-2507",
        timeout: int = 60,
        max_steps: int = 4,
        max_arg_chars: int = 8000,
        max_retries: int = 2,
        retry_base_delay: float = 1.0,
    ):
        self.base_url = base_url
        self.model = model
        self.timeout = timeout
        self.max_steps = max_steps
        self.max_arg_chars = max_arg_chars
        self.max_retries = max_retries
        self.retry_base_delay = retry_base_delay

    def _post(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """POST 請求，帶指數退避重試（連線錯誤 / 5xx）。"""
        last_exc = None
        for attempt in range(self.max_retries + 1):
            try:
                r = requests.post(self.base_url, json=payload, timeout=self.timeout)
                if r.status_code >= 500 and attempt < self.max_retries:
                    delay = self.retry_base_delay * (2 ** attempt)
                    logger.warning("[LLM] 5xx 錯誤 ({}), {}s 後重試 ({}/{})", r.status_code, delay, attempt + 1, self.max_retries)
                    time.sleep(delay)
                    continue
                r.raise_for_status()
                return r.json()
            except (requests.ConnectionError, requests.Timeout) as e:
                last_exc = e
                if attempt < self.max_retries:
                    delay = self.retry_base_delay * (2 ** attempt)
                    logger.warning("[LLM] 連線失敗 ({}), {}s 後重試 ({}/{})", type(e).__name__, delay, attempt + 1, self.max_retries)
                    time.sleep(delay)
                    continue
                raise
        raise last_exc  # type: ignore[misc]

    async def _post_async(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """非阻塞版 POST：把同步 _post 包進 asyncio.to_thread，不阻塞 event loop。"""
        return await asyncio.to_thread(self._post, payload)

    async def call_llm_async(
        self,
        *,
        messages: List[Dict[str, Any]],
        tools_schema: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[str] = None,
        temperature: float = 0.0,
    ) -> Dict[str, Any]:
        """call_llm 的非阻塞版，用於 async context（如 run_turn_stream）。"""
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if tools_schema is not None:
            payload["tools"] = tools_schema
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice
        return await self._post_async(payload)

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
        """從 LLM 回應提取第一個 tool call，支援 OpenAI 標準格式和 content fallback。"""
        msg = resp["choices"][0]["message"]

        # 正常路徑：OpenAI 標準 tool_calls 欄位
        tool_calls = msg.get("tool_calls") or []
        if tool_calls:
            return tool_calls[0]

        # Fallback：從 content 中解析 Qwen 格式的 tool call
        content = msg.get("content") or ""
        match = _TOOL_CALL_RE.search(content)
        if not match:
            return None

        try:
            raw = json.loads(match.group(1))
        except (json.JSONDecodeError, IndexError):
            return None

        name = raw.get("name")
        arguments = raw.get("arguments", {})
        if not name:
            return None

        # 清理 content 中的 raw tool call 文字，避免外洩給使用者
        cleaned = content[:match.start()].strip()
        msg["content"] = cleaned

        logger.info("[LLM] fallback 解析到 tool_call: {}", name)
        return {
            "id": "fallback_toolcall_0",
            "type": "function",
            "function": {
                "name": name,
                "arguments": json.dumps(arguments, ensure_ascii=False),
            },
        }

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
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        一個「回合」：允許 0~N 次工具呼叫，最後產出給使用者的回覆文字。
        history 由外部保存（你可以存在 SessionManager / in-memory / Redis）。

        context: 動態上下文（如購物車狀態），插在 history 之後、user 之前，
                 避免破壞 system prompt + priming 的 prefix cache。
        """
        logger.info("[LLM] 開始 run_turn: '{}'", user_text)

        # /no_think 關閉 Qwen3 thinking mode，大幅降低延遲
        messages: List[Dict[str, Any]] = [{"role": "system", "content": _NO_THINK_PREFIX + system_prompt}]
        messages.extend(_PRIMING_MESSAGES)  # few-shot priming 讓模型學會用 tool_calls
        messages.extend(history)
        if context:
            messages.append({"role": "system", "content": context})
        messages.append({"role": "user", "content": user_text})

        last_tool_trace: List[Dict[str, Any]] = []

        for _ in range(self.max_steps):
            with PerfTimer("llm_api_call"):
                resp = self.call_llm(
                    messages=messages,
                    tools_schema=tools_schema,
                    tool_choice="auto",
                    temperature=0.0,
                )
            choices = resp.get("choices") or []
            if not choices:
                logger.error("[LLM] run_turn 回傳空 choices: {}", resp)
                return {"ok": False, "error": "llm_empty_response", "assistant_text": "抱歉，請再說一次", "history": history, "tool_trace": last_tool_trace}
            msg = choices[0]["message"]
            tool_call = self.pick_first_tool_call(resp)

            if not tool_call:
                # 最終回覆（或模型決定不用工具）
                assistant_text = msg.get("content") or ""
                new_history = history + [{"role": "user", "content": user_text},
                                        {"role": "assistant", "content": assistant_text}]
                logger.info("[LLM] run_turn 完成, tool_calls={}", len(last_tool_trace))
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
            logger.info("[LLM] tool_call: {} → ok={}", tool_call.get("function", {}).get("name"), exec_result.get("ok"))
            last_tool_trace.append({"tool_call": tool_call, "exec": exec_result})

            # 3) 把工具輸出回灌給模型（role=tool）
            tool_call_id = tool_call.get("id", "toolcall_0")
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": json.dumps(exec_result, ensure_ascii=False),
            })

        logger.warning("[LLM] run_turn 超過最大步數 {}", self.max_steps)
        return {"ok": False, "error": "max_steps_exceeded", "history": history, "tool_trace": last_tool_trace}

    async def ping(
        self,
        *,
        messages: Optional[List[Dict[str, Any]]] = None,
        tools_schema: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """Warmup ping，預熱 LM Studio KV prefix cache。
        傳入完整 messages（含 system prompt + priming）才能真正 cache 住固定前綴。
        """
        try:
            warmup_messages = messages or [{"role": "user", "content": "hi"}]
            payload: Dict[str, Any] = {
                "model": self.model,
                "messages": warmup_messages,
                "temperature": 0.0,
                "max_tokens": 1,
            }
            if tools_schema is not None:
                payload["tools"] = tools_schema
            await asyncio.to_thread(self._post, payload)
        except Exception:
            pass  # warmup 失敗不影響啟動

    # ============ 串流 API ============

    async def call_llm_stream(
        self,
        *,
        messages: List[Dict[str, Any]],
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
    ) -> AsyncIterator[str]:
        """串流呼叫 LLM，逐 token yield content delta。僅用於最終文字回覆（無 tools）。"""
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream("POST", self.base_url, json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str.strip() == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                        delta = chunk["choices"][0].get("delta", {})
                        content = delta.get("content")
                        if content:
                            yield content
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue

    async def run_turn_stream(
        self,
        *,
        system_prompt: str,
        user_text: str,
        history: List[Dict[str, Any]],
        tools_schema: List[Dict[str, Any]],
        tool_map: Dict[str, Callable[..., Dict[str, Any]]],
        allowed_args: Dict[str, set],
        context: Optional[str] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        串流版 run_turn：
        - Phase 1: Tool calling 輪次（同步等完整回應，跟 run_turn 一樣）
        - Phase 2: 最終文字回覆用串流，逐 token yield
        每個 yield 是 dict：
          {"type": "tool_call", "tool_call": ..., "exec": ...}
          {"type": "text_delta", "content": "..."}
          {"type": "done", "history": [...], "tool_trace": [...]}

        context: 動態上下文（如購物車狀態），插在 history 之後、user 之前。
        """
        logger.info("[LLM] 開始 run_turn_stream: '{}'", user_text)

        # /no_think 關閉 Qwen3 thinking mode，大幅降低延遲
        messages: List[Dict[str, Any]] = [{"role": "system", "content": _NO_THINK_PREFIX + system_prompt}]
        messages.extend(_PRIMING_MESSAGES)  # few-shot priming 讓模型學會用 tool_calls
        messages.extend(history)
        if context:
            messages.append({"role": "system", "content": context})
        messages.append({"role": "user", "content": user_text})

        last_tool_trace: List[Dict[str, Any]] = []

        for _ in range(self.max_steps):
            with PerfTimer("llm_api_call"):
                resp = await self.call_llm_async(
                    messages=messages,
                    tools_schema=tools_schema,
                    tool_choice="auto",
                    temperature=0.0,
                )

            choices = resp.get("choices") or []
            if not choices:
                logger.error("[LLM] run_turn_stream 回傳空 choices: {}", resp)
                fallback = "抱歉，請再說一次"
                yield {"type": "text_delta", "content": fallback}
                yield {"type": "done", "assistant_text": fallback, "history": history, "tool_trace": last_tool_trace}
                return
            msg = choices[0]["message"]
            tool_call = self.pick_first_tool_call(resp)

            if not tool_call:
                # Phase 2：用 Phase 1 已取得的完整回覆，按標點切段 yield
                full_text = msg.get("content") or ""

                if len(full_text) <= 5:
                    if full_text:
                        yield {"type": "text_delta", "content": full_text}
                else:
                    buf = ""
                    for ch in full_text:
                        buf += ch
                        if ch in _SENTENCE_PUNCTS:
                            yield {"type": "text_delta", "content": buf}
                            buf = ""
                    if buf:
                        yield {"type": "text_delta", "content": buf}

                new_history = history + [
                    {"role": "user", "content": user_text},
                    {"role": "assistant", "content": full_text},
                ]
                yield {
                    "type": "done",
                    "assistant_text": full_text,
                    "history": new_history,
                    "tool_trace": last_tool_trace,
                }
                return

            # Tool calling 輪次
            messages.append({
                "role": "assistant",
                "content": msg.get("content"),
                "tool_calls": msg.get("tool_calls", []),
            })

            exec_result = self.execute_tool_call(
                tool_call,
                tool_map=tool_map,
                allowed_args=allowed_args,
            )
            logger.info("[LLM] tool_call: {} → ok={}", tool_call.get("function", {}).get("name"), exec_result.get("ok"))
            last_tool_trace.append({"tool_call": tool_call, "exec": exec_result})

            yield {"type": "tool_call", "tool_call": tool_call, "exec": exec_result}

            # 提前送出 tool result message 作為首段語音，大幅降低 TTFA
            # 只對加入/移除購物車觸發，避免 query_menu 等工具意外播報
            tool_name = tool_call.get("function", {}).get("name", "")
            if tool_name in _EARLY_TTS_TOOLS and exec_result.get("ok"):
                tool_result = exec_result.get("result")
                tool_msg = tool_result.get("message", "") if isinstance(tool_result, dict) else ""
                if tool_msg:
                    yield {"type": "early_tts", "content": tool_msg}

            tool_call_id = tool_call.get("id", "toolcall_0")
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": json.dumps(exec_result, ensure_ascii=False),
            })

        logger.warning("[LLM] run_turn_stream 超過最大步數 {}", self.max_steps)
        fallback = "抱歉，處理您的請求時發生問題，請再說一次"
        yield {"type": "text_delta", "content": fallback}
        yield {"type": "done", "assistant_text": fallback, "error": "max_steps_exceeded", "history": history, "tool_trace": last_tool_trace}

