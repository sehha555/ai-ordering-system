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


class OpenAICompatibleAdapter(BaseLLMAdapter):
    """OpenAI 相容 API adapter（LM Studio、vLLM、Ollama 等）"""

    def run(self, test_case: dict, timeout: float = 60) -> dict:
        base_url = self.params["base_url"]
        model = self.params["model"]
        temperature = self.params.get("temperature", 0.0)

        payload = {
            "model": model,
            "messages": test_case["messages"],
            "temperature": temperature,
        }

        if "tools" in test_case:
            payload["tools"] = test_case["tools"]
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
                tool_calls.append({
                    "name": tc["function"]["name"],
                    "arguments": json.loads(tc["function"]["arguments"]),
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
