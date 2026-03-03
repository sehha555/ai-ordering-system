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
from src.dm.tool_priming import format_tool_result

PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _build_registry():
    """建立乾淨的 ToolRegistry（共用 setup，避免重複）"""
    from src.dm.tool_registry import ToolRegistry
    from src.dm.dialogue_manager import DialogueManager
    from src.dm.session_store import InMemorySessionStore

    store = InMemorySessionStore()
    dm = DialogueManager(llm=None, store=store)
    return ToolRegistry(dm, store)


def _format_tools_for_text_mode(tools_schema: list[dict]) -> str:
    """將 tools schema 格式化為 Qwen3 原生 <tools> 文字（text mode 用）"""
    lines = [
        "\n# Tools\n",
        "You may call one or more functions to assist with the user query.\n",
        "You are provided with function signatures within <tools></tools> XML tags:",
        "<tools>",
    ]
    for tool in tools_schema:
        lines.append(json.dumps(tool, ensure_ascii=False))
    lines.append("</tools>\n")
    lines.append(
        "For each function call, return a json object with function name and arguments "
        "within <tool_call></tool_call> XML tags:\n"
        "<tool_call>\n"
        '{"name": <function-name>, "arguments": <args-json-object>}\n'
        "</tool_call>"
    )
    return "\n".join(lines)


def _load_static_context():
    """載入靜態 context（system prompt、tools schema）— 可跨 test case 快取"""
    from src.dm.system_prompts import build_system_prompt

    system_prompt = build_system_prompt()
    registry = _build_registry()
    tools_schema = registry.get_tools_schema()
    # Text mode：tools schema 嵌入 system prompt，不透過 API tools 參數
    system_prompt_with_tools = system_prompt + _format_tools_for_text_mode(tools_schema)
    return system_prompt_with_tools, tools_schema


def _load_raw_static_context():
    """載入 raw completion 用的靜態 context（system prompt 不含 tools text）"""
    from src.dm.system_prompts import build_system_prompt

    system_prompt = build_system_prompt()
    registry = _build_registry()
    tools_schema = registry.get_tools_schema()
    return system_prompt, tools_schema


def _create_fresh_tool_context():
    """每個 test case 建立新的 tool context（避免購物車狀態污染）"""
    registry = _build_registry()
    return registry.get_tool_map(), registry.get_allowed_args()


def _load_priming_messages():
    """載入 few-shot priming messages"""
    from src.dm.tool_priming import get_priming_messages
    return get_priming_messages()


class OpenAICompatibleAdapter(BaseLLMAdapter):
    """OpenAI 相容 API adapter（LM Studio、vLLM、Ollama 等）"""

    MAX_TOOL_STEPS = 4  # 對齊實際服務的 llm_tool_caller.py max_steps

    def __init__(self, params: dict):
        super().__init__(params)
        self._system_prompt = None
        self._tools_schema = None
        self._priming = None
        self._client: httpx.Client | None = None

    def _ensure_static_context(self):
        """懶載入靜態 context（system prompt、tools schema、priming）— 可跨 test case 快取"""
        if self._system_prompt is None:
            self._system_prompt, self._tools_schema = _load_static_context()
            self._priming = _load_priming_messages()

    def _parse_tool_calls(self, message: dict) -> tuple[list[dict], list[dict]]:
        """從 LLM response message 解析 tool calls（標準欄位 + Qwen content fallback）
        回傳 (tool_calls, raw_json_objs)：raw_json_objs 供 _clean_response 使用，避免重複解析"""
        tool_calls = []
        raw_json_objs = []
        if message.get("tool_calls"):
            for tc in message["tool_calls"]:
                try:
                    args = json.loads(tc["function"]["arguments"])
                except (json.JSONDecodeError, KeyError):
                    args = {}
                tool_calls.append({
                    "name": tc["function"]["name"],
                    "arguments": args,
                    "_raw": tc,  # 保留原始格式供回灌用
                })
        else:
            content = message.get("content") or ""
            raw_json_objs = _extract_json_objects(content)
            for obj in raw_json_objs:
                tool_calls.append({
                    "name": obj["name"],
                    "arguments": obj.get("arguments", {}),
                })
        return tool_calls, raw_json_objs

    def _clean_response(self, message: dict, parsed_objs: list[dict]) -> str:
        """清理 content 中的 raw tool call 文字（parsed_objs 由 _parse_tool_calls 傳入，避免重複解析）"""
        response_text = message.get("content", "") or ""
        if parsed_objs and not message.get("tool_calls"):
            response_text = re.sub(r'<\|im_start\|>', '', response_text)
            response_text = re.sub(r'</?tool_call>', '', response_text)
            for obj in parsed_objs:
                try:
                    response_text = response_text.replace(json.dumps(obj, ensure_ascii=False), '')
                except Exception:
                    pass
            response_text = response_text.strip()
        return response_text

    @staticmethod
    def _execute_tool(tool_map: dict, allowed_args: dict, name: str, arguments: dict) -> dict:
        """執行工具並回傳結果（參考 llm_tool_caller.py:152-181）

        add_to_cart 會先經過 pre-execution 驗證器：
        參數值不合法時直接回傳錯誤訊息 + 合法選項，讓模型在 tool loop 中自修正。
        """
        if name not in tool_map:
            return {"ok": False, "error": f"tool_not_allowed:{name}"}

        # add_to_cart 的 pre-execution 參數值驗證
        if name == "add_to_cart":
            from benchmarks.adapters.tool_validator import validate_add_to_cart

            validation_error = validate_add_to_cart(arguments)
            if validation_error is not None:
                logger.debug("tool_validator 攔截 add_to_cart：%s", validation_error["message"])
                return validation_error

        allowed = allowed_args.get(name, set())
        safe_args = {k: arguments[k] for k in allowed if k in arguments}
        try:
            return tool_map[name](**safe_args)
        except Exception as e:
            return {"ok": False, "error": f"tool_exec_error:{type(e).__name__}"}

    def _get_client(self, timeout: float) -> httpx.Client:
        """取得共用 httpx.Client（跨 test case 重複使用連線池）"""
        if self._client is None or self._client.is_closed:
            self._client = httpx.Client(timeout=timeout)
        return self._client

    def close(self):
        """關閉共用 httpx.Client"""
        if self._client is not None and not self._client.is_closed:
            self._client.close()

    def run(self, test_case: dict, timeout: float = 60) -> dict:
        self._ensure_static_context()
        # 每個 test case 建立新的 tool context，避免購物車狀態污染
        tool_map, allowed_args = _create_fresh_tool_context()
        base_url = self.params["base_url"]
        model = self.params["model"]
        temperature = self.params.get("temperature", 0.0)
        url = f"{base_url}/chat/completions" if not base_url.endswith("/chat/completions") else base_url

        # 從 config 讀取 sampling 參數（避免 llama.cpp 預設值干擾）
        sampling_overrides = {}
        for key in ("repeat_penalty", "min_p", "top_p", "top_k"):
            if key in self.params:
                sampling_overrides[key] = self.params[key]

        # 注入 system prompt + few-shot priming + 測試對話
        messages = [{"role": "system", "content": self._system_prompt}]
        messages.extend(self._priming)

        # 注入 session context（購物車狀態，放在 history 之後、最後 user message 之前）
        session_ctx = test_case.get("session_context")
        test_messages = list(test_case["messages"])
        if session_ctx:
            # 在最後一條 user message 之前插入 context
            ctx_text = self._format_session_context(session_ctx)
            last_user_idx = len(test_messages) - 1
            for i in range(len(test_messages) - 1, -1, -1):
                if test_messages[i]["role"] == "user":
                    last_user_idx = i
                    break
            test_messages.insert(last_user_idx, {"role": "system", "content": ctx_text})

        messages.extend(test_messages)

        # Text mode：不送 tools 參數，schema 已嵌入 system prompt
        all_tool_calls = []
        total_tokens = 0
        total_prompt_tokens = 0
        total_completion_tokens = 0
        actual_model = ""
        response_text = ""

        client = self._get_client(timeout)
        for _step in range(self.MAX_TOOL_STEPS):
            payload = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                **sampling_overrides,
            }
            # Text mode：不送 tools/tool_choice，模型用 <tool_call> 文字輸出

            logger.debug("LLM request step=%d | model=%s | messages=%d",
                         _step, model, len(messages))

            resp = client.post(url, json=payload)
            if resp.status_code != 200:
                logger.error("LLM API 回傳 %d: %s", resp.status_code, resp.text[:500])
            resp.raise_for_status()
            data = resp.json()

            # 累計 token 用量
            usage = data.get("usage", {})
            total_tokens += usage.get("total_tokens", 0)
            total_prompt_tokens += usage.get("prompt_tokens", 0)
            total_completion_tokens += usage.get("completion_tokens", 0)
            if not actual_model:
                actual_model = data.get("model", "")

            message = data["choices"][0]["message"]
            step_tool_calls, raw_objs = self._parse_tool_calls(message)

            if not step_tool_calls:
                # 沒有 tool call → 模型產出最終回覆，loop 結束
                response_text = self._clean_response(message, [])
                break

            # 有 tool call → 執行工具、回灌結果、繼續 loop
            all_tool_calls.extend(
                {"name": tc["name"], "arguments": tc["arguments"]} for tc in step_tool_calls
            )
            response_text = self._clean_response(message, raw_objs)

            # 把 assistant message 加入 messages（原始 content）
            messages.append({"role": "assistant", "content": message.get("content")})

            # 執行每個 tool call 並回灌結果（對齊 priming 格式）
            for tc_idx, tc in enumerate(step_tool_calls):
                exec_result = self._execute_tool(tool_map, allowed_args, tc["name"], tc["arguments"])
                messages.append({
                    "role": "user",
                    "content": format_tool_result(exec_result),
                })

        if actual_model and actual_model != model:
            logger.warning("模型不符！請求 %s → 實際 %s（LM Studio 可能 fallback）", model, actual_model)

        return {
            "response": response_text,
            "tool_calls": all_tool_calls,
            "actual_model": actual_model,
            "tokens": total_tokens,
            "prompt_tokens": total_prompt_tokens,
            "completion_tokens": total_completion_tokens,
        }

    @staticmethod
    def _format_session_context(ctx: dict) -> str:
        """將 test_case 的 session_context 格式化為注入文字"""
        lines = ["# 當前狀態"]
        cart_items = ctx.get("cart_items", [])
        if cart_items:
            lines.append(f"購物車（{ctx.get('cart_count', len(cart_items))} 項）：")
            for item in cart_items:
                lines.append(f"  - {item}")
        else:
            lines.append("購物車：空")
        return "\n".join(lines)


class RawCompletionAdapter(BaseLLMAdapter):
    """Raw completion adapter — 自渲染 Qwen3 template + /completion endpoint

    跳過 llama.cpp 的 chat template 渲染，用官方 Jinja2 template 產生 raw prompt，
    直接送 /completion（低階 API）。目標：對齊 LM Studio 的渲染結果。
    """

    MAX_TOOL_STEPS = 4

    def __init__(self, params: dict):
        super().__init__(params)
        self._system_prompt = None
        self._tools_schema = None
        self._priming = None
        self._renderer = None
        self._client: httpx.Client | None = None

    def _ensure_static_context(self):
        if self._system_prompt is None:
            self._system_prompt, self._tools_schema = _load_raw_static_context()
            self._priming = _load_priming_messages()
            from benchmarks.adapters.template_renderer import Qwen3TemplateRenderer
            self._renderer = Qwen3TemplateRenderer()

    def _get_client(self, timeout: float) -> httpx.Client:
        if self._client is None or self._client.is_closed:
            self._client = httpx.Client(timeout=timeout)
        return self._client

    def close(self):
        if self._client is not None and not self._client.is_closed:
            self._client.close()

    def run(self, test_case: dict, timeout: float = 60) -> dict:
        self._ensure_static_context()
        tool_map, allowed_args = _create_fresh_tool_context()
        base_url = self.params["base_url"]
        temperature = self.params.get("temperature", 0.0)

        # sampling 參數
        sampling_overrides = {}
        for key in ("repeat_penalty", "min_p", "top_p", "top_k"):
            if key in self.params:
                sampling_overrides[key] = self.params[key]

        # 組裝 messages（system + priming + test）
        messages = [{"role": "system", "content": self._system_prompt}]
        messages.extend(self._priming)

        # 注入 session context
        session_ctx = test_case.get("session_context")
        test_messages = list(test_case["messages"])
        if session_ctx:
            ctx_text = OpenAICompatibleAdapter._format_session_context(session_ctx)
            last_user_idx = len(test_messages) - 1
            for i in range(len(test_messages) - 1, -1, -1):
                if test_messages[i]["role"] == "user":
                    last_user_idx = i
                    break
            test_messages.insert(last_user_idx, {"role": "system", "content": ctx_text})

        messages.extend(test_messages)

        all_tool_calls = []
        total_tokens = 0
        total_prompt_tokens = 0
        total_completion_tokens = 0
        response_text = ""

        # /completion endpoint（不含 /v1）
        url = f"{base_url}/completion"

        client = self._get_client(timeout)
        for _step in range(self.MAX_TOOL_STEPS):
            # 渲染 raw prompt
            prompt = self._renderer.render_prompt(
                messages, self._tools_schema, enable_thinking=False,
            )

            payload = {
                "prompt": prompt,
                "stop": ["<|im_end|>"],
                "n_predict": 2048,
                "temperature": temperature,
                "cache_prompt": True,
                **sampling_overrides,
            }

            logger.debug("Raw completion step=%d | prompt_len=%d chars", _step, len(prompt))

            resp = client.post(url, json=payload)
            if resp.status_code != 200:
                logger.error("/completion API 回傳 %d: %s", resp.status_code, resp.text[:500])
            resp.raise_for_status()
            data = resp.json()

            # Token 用量（/completion 的欄位名不同）
            total_prompt_tokens += data.get("tokens_evaluated", 0)
            total_completion_tokens += data.get("tokens_predicted", 0)
            total_tokens += data.get("tokens_evaluated", 0) + data.get("tokens_predicted", 0)

            content = data.get("content", "")

            # 解析 tool calls
            raw_objs = _extract_json_objects(content)
            step_tool_calls = [
                {"name": obj["name"], "arguments": obj.get("arguments", {})}
                for obj in raw_objs
            ]

            if not step_tool_calls:
                # 沒有 tool call → 最終回覆
                response_text = self._clean_content(content)
                break

            # 有 tool call → 執行工具、回灌結果
            all_tool_calls.extend(step_tool_calls)
            response_text = self._clean_content(content, raw_objs)

            # 把 assistant 回覆加入 messages（保持原始 content 以便下輪渲染）
            messages.append({"role": "assistant", "content": content})

            for tc in step_tool_calls:
                exec_result = OpenAICompatibleAdapter._execute_tool(
                    tool_map, allowed_args, tc["name"], tc["arguments"],
                )
                # 以 role:tool + plain JSON 加入（renderer 會轉為 <tool_response>）
                result_json = json.dumps(exec_result, ensure_ascii=False)
                messages.append({"role": "tool", "content": result_json})

        return {
            "response": response_text,
            "tool_calls": all_tool_calls,
            "actual_model": self.params.get("model", ""),
            "tokens": total_tokens,
            "prompt_tokens": total_prompt_tokens,
            "completion_tokens": total_completion_tokens,
        }

    @staticmethod
    def _clean_content(content: str, parsed_objs: list[dict] | None = None) -> str:
        """清理 content 中的 tool call 文字"""
        text = content
        text = re.sub(r'<\|im_start\|>', '', text)
        text = re.sub(r'</?tool_call>', '', text)
        text = re.sub(r'<think>\s*</think>', '', text)
        if parsed_objs:
            for obj in parsed_objs:
                try:
                    text = text.replace(json.dumps(obj, ensure_ascii=False), '')
                except Exception:
                    pass
        return text.strip()


REGISTRY = {
    "openai_compatible": OpenAICompatibleAdapter,
    "raw_completion": RawCompletionAdapter,
}


def create_llm_adapter(adapter_name: str, params: dict) -> BaseLLMAdapter:
    cls = REGISTRY.get(adapter_name)
    if cls is None:
        raise ValueError(f"未知的 LLM adapter: {adapter_name}，可用: {list(REGISTRY.keys())}")
    return cls(params)
