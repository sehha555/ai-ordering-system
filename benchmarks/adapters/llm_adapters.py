"""
LLM 模型 Adapters
新增 LLM 模型：1) 建立子類別 2) 在 REGISTRY 註冊
"""
import json
import sys
from pathlib import Path

import httpx

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


class OpenAICompatibleAdapter(BaseLLMAdapter):
    """OpenAI 相容 API adapter（LM Studio、vLLM、Ollama 等）"""

    def __init__(self, params: dict):
        super().__init__(params)
        self._system_prompt = None
        self._tools_schema = None

    def _ensure_context(self):
        """懶載入 system prompt 和 tools schema"""
        if self._system_prompt is None:
            self._system_prompt, self._tools_schema = _load_system_prompt_and_tools()

    def run(self, test_case: dict, timeout: float = 60) -> dict:
        self._ensure_context()
        base_url = self.params["base_url"]
        model = self.params["model"]
        temperature = self.params.get("temperature", 0.0)

        # 注入 system prompt
        messages = [{"role": "system", "content": self._system_prompt}]
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

        with httpx.Client(timeout=timeout) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()

        choice = data["choices"][0]
        message = choice["message"]

        tool_calls = []
        if message.get("tool_calls"):
            for tc in message["tool_calls"]:
                try:
                    args = json.loads(tc["function"]["arguments"])
                except (json.JSONDecodeError, KeyError):
                    args = {}
                tool_calls.append({
                    "name": tc["function"]["name"],
                    "arguments": args,
                })

        return {
            "response": message.get("content", ""),
            "tool_calls": tool_calls,
            "tokens": data.get("usage", {}).get("total_tokens", 0),
        }


REGISTRY = {
    "openai_compatible": OpenAICompatibleAdapter,
}


def create_llm_adapter(adapter_name: str, params: dict) -> BaseLLMAdapter:
    cls = REGISTRY.get(adapter_name)
    if cls is None:
        raise ValueError(f"未知的 LLM adapter: {adapter_name}，可用: {list(REGISTRY.keys())}")
    return cls(params)
