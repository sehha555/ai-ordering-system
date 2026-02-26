"""
LLM 模型 Adapters
新增 LLM 模型：1) 建立子類別 2) 在 REGISTRY 註冊
"""
import json
import logging
import re
import sys
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

# Qwen 模型有時把 tool call 輸出到 content 而非 tool_calls 欄位
_TOOL_CALL_PREFIX_RE = re.compile(r'[<\|im_start\|>]*\s*(?:<tool_call>\s*)?(\{)', re.DOTALL)


def _extract_json_objects(text: str) -> list[dict]:
    """從文字中提取所有含 "name" 的 JSON 物件（支援巢狀括號）"""
    results = []
    for m in _TOOL_CALL_PREFIX_RE.finditer(text):
        start = m.start(1)
        depth = 0
        end = start
        for i in range(start, len(text)):
            if text[i] == '{':
                depth += 1
            elif text[i] == '}':
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        if depth == 0 and end > start:
            try:
                obj = json.loads(text[start:end])
                if "name" in obj:
                    results.append(obj)
            except json.JSONDecodeError:
                continue
    return results

from benchmarks.adapters.base import BaseLLMAdapter

PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _load_system_prompt_and_tools():
    """載入系統提示詞和工具 schema（用於 benchmark 測試）"""
    from src.dm.system_prompts import build_system_prompt
    from src.dm.tool_registry import ToolRegistry
    from src.dm.dialogue_manager import DialogueManager
    from src.dm.session_store import InMemorySessionStore

    system_prompt = build_system_prompt()
    store = InMemorySessionStore()
    dm = DialogueManager(llm=None, store=store)
    registry = ToolRegistry(dm, store)
    tools_schema = registry.get_tools_schema()

    return system_prompt, tools_schema


def _load_priming_messages():
    """載入 few-shot priming messages"""
    from src.dm.tool_priming import get_priming_messages
    return get_priming_messages()


class OpenAICompatibleAdapter(BaseLLMAdapter):
    """OpenAI 相容 API adapter（LM Studio、vLLM、Ollama 等）"""

    def __init__(self, params: dict):
        super().__init__(params)
        self._system_prompt = None
        self._tools_schema = None
        self._priming = None

    def _ensure_context(self):
        """懶載入 system prompt、tools schema 和 priming"""
        if self._system_prompt is None:
            self._system_prompt, self._tools_schema = _load_system_prompt_and_tools()
            self._priming = _load_priming_messages()

    def run(self, test_case: dict, timeout: float = 60) -> dict:
        self._ensure_context()
        base_url = self.params["base_url"]
        model = self.params["model"]
        temperature = self.params.get("temperature", 0.0)

        # 注入 system prompt + few-shot priming
        messages = [{"role": "system", "content": self._system_prompt}]
        messages.extend(self._priming)
        messages.extend(test_case["messages"])

        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }

        # 注入 tools schema（除非測試案例明確提供自己的 tools）
        tools = test_case.get("tools", self._tools_schema)
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        url = f"{base_url}/chat/completions" if not base_url.endswith("/chat/completions") else base_url

        logger.debug("LLM request → %s | model=%s | messages=%d | tools=%d",
                      url, model, len(messages), len(tools) if tools else 0)
        logger.debug("Payload: %s", json.dumps(payload, ensure_ascii=False, default=str)[:2000])

        with httpx.Client(timeout=timeout) as client:
            resp = client.post(url, json=payload)
            if resp.status_code != 200:
                logger.error("LLM API 回傳 %d: %s", resp.status_code, resp.text[:500])
            resp.raise_for_status()
            data = resp.json()

        choice = data["choices"][0]
        message = choice["message"]

        tool_calls = []
        if message.get("tool_calls"):
            # 標準 OpenAI tool_calls 欄位
            for tc in message["tool_calls"]:
                try:
                    args = json.loads(tc["function"]["arguments"])
                except (json.JSONDecodeError, KeyError):
                    args = {}
                tool_calls.append({
                    "name": tc["function"]["name"],
                    "arguments": args,
                })
        else:
            # Fallback：從 content 中解析 Qwen 格式的 tool call（支援巢狀 JSON）
            content = message.get("content") or ""
            for obj in _extract_json_objects(content):
                tool_calls.append({
                    "name": obj["name"],
                    "arguments": obj.get("arguments", {}),
                })

        # 清理 content 中的 raw tool call 文字
        response_text = message.get("content", "")
        if tool_calls and not message.get("tool_calls"):
            # 移除 <|im_start|> 和 tool call JSON 殘留
            response_text = re.sub(r'<\|im_start\|>', '', response_text)
            response_text = re.sub(r'</?tool_call>', '', response_text)
            for obj in _extract_json_objects(message.get("content", "")):
                try:
                    response_text = response_text.replace(json.dumps(obj, ensure_ascii=False), '')
                except Exception:
                    pass
            response_text = response_text.strip()

        usage = data.get("usage", {})
        return {
            "response": response_text,
            "tool_calls": tool_calls,
            "tokens": usage.get("total_tokens", 0),
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
        }


REGISTRY = {
    "openai_compatible": OpenAICompatibleAdapter,
}


def create_llm_adapter(adapter_name: str, params: dict) -> BaseLLMAdapter:
    cls = REGISTRY.get(adapter_name)
    if cls is None:
        raise ValueError(f"未知的 LLM adapter: {adapter_name}，可用: {list(REGISTRY.keys())}")
    return cls(params)
