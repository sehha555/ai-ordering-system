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
_PER_STEP_TIMEOUT = 15.0  # run_turn_stream 每步 LLM 呼叫上限（秒）

from src.utils import SENTENCE_PUNCTS as _SENTENCE_PUNCTS

# Qwen 模型有時把 tool call 輸出到 content 而非 tool_calls 欄位
_TOOL_CALL_RE = re.compile(
    r"[<\|im_start\|>]*\s*"  # 可選的 <|im_start|> 前綴
    r"(?:<tool_call>\s*)?"  # 可選的 <tool_call> 標籤
    r'(\{["\s]*"?name"?\s*:.*?\})'  # JSON body
    r"\s*(?:</tool_call>)?",  # 可選的 </tool_call> 標籤
    re.DOTALL,
)

# Qwen3.5-9B 常見的「系統有問題」幻覺清除
_APOLOGY_SYSTEM_RE = re.compile(
    r"[，。！]?\s*(?:不好意思|抱歉|對不起)[^。！]*(?:系統|有問題|出錯|故障|異常)[^。！]*[。！]?"
)


def _strip_hallucinated_apology(text: str) -> str:
    """移除模型在 tool result 後幻想出的系統錯誤道歉"""
    return _APOLOGY_SYSTEM_RE.sub("", text).strip()


def _is_followup_question(text: str) -> bool:
    """判斷是否為追問缺資訊的問句（vs 通用「還要什麼」確認）"""
    if "？" not in text:
        return False
    # 移除通用確認語（不算追問）
    cleaned = re.sub(r"還要什麼[嗎？]*", "", text)
    cleaned = re.sub(r"還需要什麼[嗎？]*", "", cleaned)
    cleaned = re.sub(r"好[，,～~]?\s*", "", cleaned)
    # 清理後仍有「？」→ 是追問缺資訊
    return "？" in cleaned


def _apply_response_template(model_text: str, tool_trace: List[Dict[str, Any]]) -> str:
    """Response Template：ok:true 後用 code 構建回覆，取代模型生成。

    規則：
    - 最後一個 tool exec 是 ok:true 且有 message → 替換為 template
    - 模型在追問缺資訊（非通用確認）→ 保留
    - ok:false / 無 tool call → 保留模型回覆
    """
    if not tool_trace:
        return model_text

    last_exec = tool_trace[-1].get("exec", {})
    if not last_exec.get("ok"):
        return model_text

    # 模型在追問缺資訊 → 保留
    if _is_followup_question(model_text):
        return model_text

    tool_result = last_exec.get("result")
    tool_msg = tool_result.get("message", "") if isinstance(tool_result, dict) else ""
    if not tool_msg:
        return model_text

    return f"好，{tool_msg}～還要什麼？"


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

    def _build_payload(
        self,
        messages: List[Dict[str, Any]],
        *,
        temperature: float = 0.3,
        stream: bool = False,
        tools_schema: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[str] = None,
        max_tokens: Optional[int] = None,
    ) -> Dict[str, Any]:
        """共用 payload 建構（sampling 參數統一管理）"""
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "top_p": 0.8,
            "top_k": 20,
            "min_p": 0.01,
        }
        if stream:
            payload["stream"] = True
        if tools_schema is not None:
            payload["tools"] = tools_schema
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        return payload

    def _post(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """POST 請求，帶指數退避重試（連線錯誤 / 5xx）。"""
        last_exc = None
        for attempt in range(self.max_retries + 1):
            try:
                r = requests.post(self.base_url, json=payload, timeout=self.timeout)
                if r.status_code >= 500 and attempt < self.max_retries:
                    delay = self.retry_base_delay * (2**attempt)
                    logger.warning(
                        "[LLM] 5xx 錯誤 ({}), {}s 後重試 ({}/{})",
                        r.status_code,
                        delay,
                        attempt + 1,
                        self.max_retries,
                    )
                    time.sleep(delay)
                    continue
                r.raise_for_status()
                return r.json()
            except (requests.ConnectionError, requests.Timeout) as e:
                last_exc = e
                if attempt < self.max_retries:
                    delay = self.retry_base_delay * (2**attempt)
                    logger.warning(
                        "[LLM] 連線失敗 ({}), {}s 後重試 ({}/{})",
                        type(e).__name__,
                        delay,
                        attempt + 1,
                        self.max_retries,
                    )
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
        temperature: float = 0.3,
    ) -> Dict[str, Any]:
        """call_llm 的非阻塞版，用於 async context（如 run_turn_stream）。"""
        return await self._post_async(
            self._build_payload(
                messages,
                temperature=temperature,
                tools_schema=tools_schema,
                tool_choice=tool_choice,
            )
        )

    def call_llm(
        self,
        *,
        messages: List[Dict[str, Any]],
        tools_schema: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[str] = None,  # "auto" | "required" | {"type":"function",...}
        temperature: float = 0.3,
    ) -> Dict[str, Any]:
        return self._post(
            self._build_payload(
                messages,
                temperature=temperature,
                tools_schema=tools_schema,
                tool_choice=tool_choice,
            )
        )

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
        cleaned = content[: match.start()].strip()
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
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": _NO_THINK_PREFIX + system_prompt}
        ]
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
                )
            choices = resp.get("choices") or []
            if not choices:
                logger.error("[LLM] run_turn 回傳空 choices: {}", resp)
                return {
                    "ok": False,
                    "error": "llm_empty_response",
                    "assistant_text": "抱歉，請再說一次",
                    "history": history,
                    "tool_trace": last_tool_trace,
                }
            msg = choices[0]["message"]
            tool_call = self.pick_first_tool_call(resp)

            if not tool_call:
                # 最終回覆（或模型決定不用工具）
                assistant_text = _strip_hallucinated_apology(msg.get("content") or "")

                # Response Template：ok:true 後用 code 構建回覆，取代模型生成
                assistant_text = _apply_response_template(assistant_text, last_tool_trace)

                new_history = history + [
                    {"role": "user", "content": user_text},
                    {"role": "assistant", "content": assistant_text},
                ]
                logger.info("[LLM] run_turn 完成, tool_calls={}", len(last_tool_trace))
                return {
                    "ok": True,
                    "assistant_text": assistant_text,
                    "history": new_history,
                    "tool_trace": last_tool_trace,
                }

            # 1) 把模型的 tool_call 記到 messages（OpenAI 協議習慣是 assistant 帶 tool_calls）
            messages.append(
                {
                    "role": "assistant",
                    "content": msg.get("content"),
                    "tool_calls": msg.get("tool_calls", []),
                }
            )

            # 2) 執行工具
            exec_result = self.execute_tool_call(
                tool_call,
                tool_map=tool_map,
                allowed_args=allowed_args,
            )
            logger.info(
                "[LLM] tool_call: {} → ok={}",
                tool_call.get("function", {}).get("name"),
                exec_result.get("ok"),
            )
            last_tool_trace.append({"tool_call": tool_call, "exec": exec_result})

            # 3) 把工具輸出回灌給模型（role=tool）
            tool_call_id = tool_call.get("id", "toolcall_0")
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": json.dumps(exec_result, ensure_ascii=False),
                }
            )

            # 4) ok:true 時 assistant prefill 引導正確回覆格式（避免「系統有問題」幻覺）
            if exec_result.get("ok"):
                messages.append({"role": "assistant", "content": "好，", "prefix": True})

        logger.warning("[LLM] run_turn 超過最大步數 {}", self.max_steps)
        return {
            "ok": False,
            "error": "max_steps_exceeded",
            "history": history,
            "tool_trace": last_tool_trace,
        }

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
            payload = self._build_payload(
                warmup_messages,
                temperature=0.0,
                max_tokens=1,
                tools_schema=tools_schema,
            )
            await asyncio.to_thread(self._post, payload)
        except Exception:
            pass  # warmup 失敗不影響啟動

    # ============ 串流 API ============

    async def call_llm_stream(
        self,
        *,
        messages: List[Dict[str, Any]],
        temperature: float = 0.3,
        max_tokens: Optional[int] = None,
    ) -> AsyncIterator[str]:
        """串流呼叫 LLM，逐 token yield content delta。僅用於最終文字回覆（無 tools）。"""
        payload = self._build_payload(
            messages, temperature=temperature, stream=True, max_tokens=max_tokens
        )
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

    async def call_llm_stream_with_tools(
        self,
        *,
        messages: List[Dict[str, Any]],
        tools_schema: List[Dict[str, Any]],
        tool_choice: str = "auto",
        temperature: float = 0.3,
    ) -> AsyncIterator[Dict[str, Any]]:
        """串流 LLM 呼叫，同時處理 tool_calls delta 和 content delta。

        Yields:
          {"type": "content_delta", "content": "..."}
          {"type": "tool_call_complete", "tool_calls": [...], "raw_message": {...}}
          {"type": "stream_done", "finish_reason": "...", "raw_message": {...}}
        """
        payload = self._build_payload(
            messages,
            temperature=temperature,
            stream=True,
            tools_schema=tools_schema,
            tool_choice=tool_choice,
        )
        # 累積 tool_calls delta（index → {id, name, arguments}）
        tool_calls_acc: Dict[int, Dict[str, str]] = {}
        content_acc = ""
        finish_reason = None

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
                    except json.JSONDecodeError:
                        continue
                    choice = chunk.get("choices", [{}])[0]
                    delta = choice.get("delta", {})
                    finish_reason = choice.get("finish_reason") or finish_reason

                    # Tool call delta 累積
                    if delta.get("tool_calls"):
                        for tc_delta in delta["tool_calls"]:
                            idx = tc_delta.get("index", 0)
                            if idx not in tool_calls_acc:
                                tool_calls_acc[idx] = {
                                    "id": tc_delta.get("id", f"toolcall_{idx}"),
                                    "name": "",
                                    "arguments": "",
                                }
                            acc = tool_calls_acc[idx]
                            fn = tc_delta.get("function", {})
                            if fn.get("name"):
                                acc["name"] += fn["name"]
                            if fn.get("arguments"):
                                acc["arguments"] += fn["arguments"]

                    # Content delta 即時 yield
                    content = delta.get("content")
                    if content:
                        content_acc += content
                        yield {"type": "content_delta", "content": content}

        # 組裝 raw_message（模擬非串流回覆格式，供 pick_first_tool_call 使用）
        raw_message: Dict[str, Any] = {"content": content_acc or None}
        if tool_calls_acc:
            raw_message["tool_calls"] = [
                {
                    "id": acc["id"],
                    "type": "function",
                    "function": {"name": acc["name"], "arguments": acc["arguments"]},
                }
                for acc in tool_calls_acc.values()
            ]
            yield {
                "type": "tool_call_complete",
                "tool_calls": raw_message["tool_calls"],
                "raw_message": raw_message,
            }
        yield {"type": "stream_done", "finish_reason": finish_reason, "raw_message": raw_message}

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
        串流版 run_turn — 逐 token 串流，邊收邊切句送 TTS：
        - Tool call 路徑：累積 tool_calls delta 直到完整 → 執行工具 → early_tts
        - 純文字路徑：逐 token 累積 → 遇句點即 yield text_delta → orchestrator 立即送 TTS
        每個 yield 是 dict：
          {"type": "tool_call", "tool_call": ..., "exec": ...}
          {"type": "early_tts", "content": "..."}
          {"type": "text_delta", "content": "..."}
          {"type": "done", "history": [...], "tool_trace": [...]}
          {"type": "fallback", "content": "..."}

        context: 動態上下文（如購物車狀態），插在 history 之後、user 之前。
        """
        logger.info("[LLM] 開始 run_turn_stream: '{}'", user_text)

        # /no_think 關閉 Qwen3 thinking mode，大幅降低延遲
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": _NO_THINK_PREFIX + system_prompt}
        ]
        messages.extend(_PRIMING_MESSAGES)  # few-shot priming 讓模型學會用 tool_calls
        messages.extend(history)
        if context:
            messages.append({"role": "system", "content": context})
        messages.append({"role": "user", "content": user_text})

        last_tool_trace: List[Dict[str, Any]] = []

        for step in range(self.max_steps):
            content_buf = ""
            sentence_buf = ""
            tool_calls = None
            raw_message = None

            # early_tts 已送出時，靜默緩衝不 yield text_delta（避免 TTS 重複播放）
            early_tts_sent = bool(last_tool_trace and last_tool_trace[-1].get("exec", {}).get("ok"))

            try:
                with PerfTimer("llm_api_call"):
                    async with asyncio.timeout(_PER_STEP_TIMEOUT):
                        async for evt in self.call_llm_stream_with_tools(
                            messages=messages,
                            tools_schema=tools_schema,
                        ):
                            if evt["type"] == "content_delta":
                                content_buf += evt["content"]
                                sentence_buf += evt["content"]
                                if not early_tts_sent:
                                    # 遇到句點 → 立即 yield text_delta（orchestrator 送 TTS）
                                    while sentence_buf:
                                        idx = next(
                                            (
                                                i
                                                for i, ch in enumerate(sentence_buf)
                                                if ch in _SENTENCE_PUNCTS
                                            ),
                                            -1,
                                        )
                                        if idx == -1:
                                            break
                                        sentence = sentence_buf[: idx + 1]
                                        sentence_buf = sentence_buf[idx + 1 :]
                                        if sentence.strip():
                                            yield {"type": "text_delta", "content": sentence}

                            elif evt["type"] == "tool_call_complete":
                                tool_calls = evt["tool_calls"]
                                raw_message = evt["raw_message"]

                            elif evt["type"] == "stream_done":
                                if raw_message is None:
                                    raw_message = evt["raw_message"]

            except Exception as exc:
                if isinstance(exc, asyncio.TimeoutError):
                    logger.warning(
                        "[LLM] run_turn_stream step {} timeout ({:.0f}s)", step, _PER_STEP_TIMEOUT
                    )
                    fallback = "不好意思，我需要多一點時間處理，請再說一次好嗎？"
                else:
                    logger.error("[LLM] run_turn_stream step {} 異常: {}", step, exc)
                    fallback = "不好意思，系統暫時無法處理，請稍後再試"
                yield {"type": "fallback", "content": fallback}
                yield {
                    "type": "done",
                    "assistant_text": fallback,
                    "history": history,
                    "tool_trace": last_tool_trace,
                }
                return

            # 殘餘文字（未遇到句點的尾巴）
            if sentence_buf.strip() and not early_tts_sent:
                yield {"type": "text_delta", "content": sentence_buf}

            if not tool_calls:
                full_text = _strip_hallucinated_apology(content_buf)
                full_text = _apply_response_template(full_text, last_tool_trace)

                # early_tts 已處理 TTS，只在模型追問缺資訊時才補 yield
                if early_tts_sent and _is_followup_question(full_text):
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

            # Tool calling 路徑 — 驗證 tool_call 後才加入 messages（避免 history 不一致）
            tool_call = tool_calls[0] if tool_calls else None

            # Fallback：嘗試從 content 中解析 Qwen 格式 tool call
            if tool_call and not tool_call.get("function", {}).get("name"):
                fake_resp = {"choices": [{"message": raw_message}]}
                tool_call = self.pick_first_tool_call(fake_resp)

            if not tool_call:
                # tool_calls delta 不完整，跳過此步（不汙染 messages）
                continue

            messages.append(
                {
                    "role": "assistant",
                    "content": raw_message.get("content") if raw_message else None,
                    "tool_calls": tool_calls,
                }
            )

            exec_result = self.execute_tool_call(
                tool_call,
                tool_map=tool_map,
                allowed_args=allowed_args,
            )
            logger.info(
                "[LLM] tool_call: {} → ok={}",
                tool_call.get("function", {}).get("name"),
                exec_result.get("ok"),
            )
            last_tool_trace.append({"tool_call": tool_call, "exec": exec_result})

            yield {"type": "tool_call", "tool_call": tool_call, "exec": exec_result}

            # 提前送出 Response Template 作為首段語音，大幅降低 TTFA
            tool_result_data = exec_result.get("result")
            tool_msg = (
                tool_result_data.get("message", "") if isinstance(tool_result_data, dict) else ""
            )
            if exec_result.get("ok") and tool_msg:
                yield {"type": "early_tts", "content": f"好，{tool_msg}～還要什麼？"}

            tool_call_id = tool_call.get("id", "toolcall_0")
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": json.dumps(exec_result, ensure_ascii=False),
                }
            )

            # ok:true 時 assistant prefill 引導正確回覆格式
            if exec_result.get("ok"):
                messages.append({"role": "assistant", "content": "好，", "prefix": True})

        logger.warning("[LLM] run_turn_stream 超過最大步數 {}", self.max_steps)
        fallback = "抱歉，處理您的請求時發生問題，請再說一次"
        yield {"type": "text_delta", "content": fallback}
        yield {
            "type": "done",
            "assistant_text": fallback,
            "error": "max_steps_exceeded",
            "history": history,
            "tool_trace": last_tool_trace,
        }
