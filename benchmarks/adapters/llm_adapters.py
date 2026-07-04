"""
LLM 模型 Adapters
新增 LLM 模型：1) 建立子類別 2) 在 REGISTRY 註冊
"""

import json
import logging
import os
import re
import sys
import time  # noqa: E402
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

# Qwen 模型有時把 tool call 輸出到 content 而非 tool_calls 欄位
_TOOL_CALL_PREFIX_RE = re.compile(r"[<\|im_start\|>]*\s*(?:<tool_call>\s*)?(\{)", re.DOTALL)

# Text Tag 模式正則（與 voice_router.py 保持一致）
_ADD_RE = re.compile(r"\[ADD:([^\]]+)\]")
_QUERY_RE = re.compile(r"\[QUERY(?::([^\]]*))?\]")


def _extract_json_objects(text: str) -> list[dict]:
    """從文字中提取所有含 "name" 的 JSON 物件（支援巢狀括號）"""
    results = []
    for m in _TOOL_CALL_PREFIX_RE.finditer(text):
        start = m.start(1)
        depth = 0
        end = start
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
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


def _build_registry():
    """建立乾淨的 ToolRegistry（共用 setup，避免重複）"""
    from src.dm.tool_registry import ToolRegistry
    from src.dm.dialogue_manager import DialogueManager
    from src.dm.session_store import InMemorySessionStore

    store = InMemorySessionStore()
    dm = DialogueManager(llm=None, store=store)
    return ToolRegistry(dm, store)


def _load_static_context():
    """載入靜態 context（system prompt + tools schema），兩個 adapter 共用"""
    from src.dm.system_prompts import build_system_prompt

    system_prompt = build_system_prompt()
    registry = _build_registry()
    tools_schema = registry.get_tools_schema()
    return system_prompt, tools_schema


def _create_fresh_tool_context(session_context: dict | None = None):
    """每個 test case 建立新的 tool context（避免購物車狀態污染）

    若 session_context 含 cart_items，會預填購物車讓 checkout 場景能正常運作。
    """
    from src.dm.session_store import InMemorySessionStore

    store = InMemorySessionStore()
    from src.dm.dialogue_manager import DialogueManager
    from src.dm.tool_registry import ToolRegistry

    dm = DialogueManager(llm=None, store=store)
    registry = ToolRegistry(dm, store)
    registry.set_session_id("benchmark_test")

    # 預填購物車（checkout 等場景需要）
    if session_context and session_context.get("cart_items"):
        cart = []
        for i, item_text in enumerate(session_context["cart_items"]):
            # 解析 "起司蛋餅 x1" 格式
            name = item_text.split(" x")[0] if " x" in item_text else item_text
            cart.append(
                {
                    "item_id": f"pre_{i + 1}",
                    "itemtype": "preloaded",
                    "flavor": name,
                    "quantity": 1,
                }
            )
        store.set("benchmark_test", {"cart": cart})

    return registry.get_tool_map(), registry.get_allowed_args()


def _load_priming_messages():
    """載入 few-shot priming messages"""
    from src.dm.tool_priming import get_priming_messages

    return get_priming_messages()


def _clean_content(content: str, parsed_objs: list[dict] | None = None) -> str:
    """清理 content 中的 raw tool call 文字 + 模型幻覺（兩個 adapter 共用）"""
    text = content or ""
    text = re.sub(r"<\|im_start\|>", "", text)
    text = re.sub(r"</?tool_call>", "", text)
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    if parsed_objs:
        for obj in parsed_objs:
            try:
                text = text.replace(json.dumps(obj, ensure_ascii=False), "")
            except Exception:
                pass
    # 清除 Qwen3.5-9B 常見的「系統有問題」幻覺
    text = re.sub(
        r"[，。！]?\s*不好意思[^。！]*(?:系統|有問題|出錯|故障|異常)[^。！]*[。！]?", "", text
    )
    text = re.sub(
        r"[，。！]?\s*(?:抱歉|對不起)[^。！]*(?:系統|有問題|出錯|故障|異常)[^。！]*[。！]?",
        "",
        text,
    )
    return text.strip()


def _execute_tool(tool_map: dict, allowed_args: dict, name: str, arguments: dict) -> dict:
    """執行工具並回傳結果

    add_item 會先經過 pre-execution 驗證器：
    參數值不合法時直接回傳錯誤訊息 + 合法選項，讓模型在 tool loop 中自修正。
    """
    if name not in tool_map:
        return {"ok": False, "error": f"tool_not_allowed:{name}"}

    if name == "add_item":
        from benchmarks.adapters.tool_validator_unified import validate_add_item

        validation_error = validate_add_item(arguments)
        if validation_error is not None:
            logger.debug("tool_validator_unified 攔截 add_item：%s", validation_error["message"])
            return validation_error

    allowed = allowed_args.get(name, set())
    safe_args = {k: arguments[k] for k in allowed if k in arguments}
    try:
        return tool_map[name](**safe_args)
    except Exception as e:
        return {"ok": False, "error": f"tool_exec_error:{type(e).__name__}"}


def _is_followup_question(text: str) -> bool:
    """判斷是否為追問缺資訊的問句（vs 通用「還要什麼」確認）"""
    if "？" not in text:
        return False
    cleaned = re.sub(r"還要什麼[嗎？]*", "", text)
    cleaned = re.sub(r"還需要什麼[嗎？]*", "", cleaned)
    cleaned = re.sub(r"好[，,～~]?\s*", "", cleaned)
    return "？" in cleaned


def _apply_response_template(model_text: str, tool_calls: list, exec_results: list) -> str:
    """Response Template：ok:true 後用 code 構建回覆（對齊 production llm_tool_caller.py）

    query_menu ok:true → 保留 model 的品項列表文字（不覆蓋）
    add_item ok:true → 一律套用 template（不保留 model text，避免遺失品項資訊）
      - 多個 ok:true：用第一個 ok:true 的 message（保留主要品項資訊）
    ok:false → 用 tool_msg 構建追問（比 model 的「好～還要什麼？」更精確）
      - 多個 exec：用最後一個 ok:false 的 message
    """
    if not tool_calls or not exec_results:
        return model_text

    # query_menu ok:true → 保留 model 文字（品項列表由 model 生成，不覆蓋）
    if any(tc["name"] == "query_menu" for tc in tool_calls):
        return model_text

    # 找第一個 ok:true
    first_ok = next((r for r in exec_results if r.get("ok")), None)
    if first_ok:
        tool_msg = first_ok.get("message", "")
        if not tool_msg:
            return model_text
        # 保留 [CHECKOUT]：production 中結帳 tag 於 ADD 之前已被攔截處理，
        # template 覆蓋不應吞掉模型的結帳意圖（複合單句點餐+結帳場景）
        prefix = "[CHECKOUT]" if "[CHECKOUT]" in model_text else ""
        return f"{prefix}好，{tool_msg}～還要什麼？"

    # 全部 ok:false：用最後一個 ok:false 的 tool_msg 構建追問
    last_exec = exec_results[-1]
    tool_msg = last_exec.get("message", "")
    if tool_msg:
        # 避免重複問號（tool_msg 本身已含問號時不再加）
        suffix = "" if tool_msg.endswith("？") else "？"
        return f"請問{tool_msg}{suffix}"

    return model_text


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

    # 舊格式：sold_out 為 list
    sold_out = ctx.get("sold_out", [])
    if sold_out:
        lines.append(f"\n【售完資訊】\n售完：{'、'.join(sold_out)}")

    # 新格式：sold_out_categories 為 dict，支援整類或特定選項售完
    sold_out_categories = ctx.get("sold_out_categories", {})
    if sold_out_categories:
        sold_items = []
        option_restrictions = []
        for category, value in sold_out_categories.items():
            if value is True:
                sold_items.append(category)
            elif isinstance(value, list):
                # 選項售完：轉為「xx（yy 選項）」格式放入 售完 清單
                for opt in value:
                    sold_items.append(f"{opt}（{category}選項）")
                # 同時加選項限制說明
                option_restrictions.append(f"{category}：{' 和 '.join(value)}不可選")
        sold_out_block = ["【售完資訊】（優先級最高，違反以下規則視為錯誤）"]
        if sold_items:
            sold_out_block.append(f"售完：{'、'.join(sold_items)}")
        if option_restrictions:
            for category, value in sold_out_categories.items():
                if isinstance(value, list):
                    avail_hint = (
                        "紫米或混米" if category == "飯糰米種" and "白米" in value else "其他選項"
                    )
                    sold_out_block.append(
                        f"[規則] 若客人點{'、'.join(value)}，需回覆：{'、'.join(value)}售完，目前只有{avail_hint}，絕不能自己替換"
                    )
        lines.append("\n" + "\n".join(sold_out_block))

    return "\n".join(lines)


def _inject_session_context(test_messages: list[dict], session_ctx: dict | None) -> list[dict]:
    """在最後一條 user message 之前插入 session context（兩個 adapter 共用）"""
    if not session_ctx:
        return test_messages
    result = list(test_messages)
    ctx_text = _format_session_context(session_ctx)
    last_user_idx = len(result) - 1
    for i in range(len(result) - 1, -1, -1):
        if result[i]["role"] == "user":
            last_user_idx = i
            break
    result[last_user_idx] = dict(result[last_user_idx])
    result[last_user_idx]["content"] = ctx_text + "\n\n" + result[last_user_idx]["content"]
    return result


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
        回傳 (tool_calls, raw_json_objs)：raw_json_objs 供 _clean_content 使用，避免重複解析"""
        tool_calls = []
        raw_json_objs = []
        if message.get("tool_calls"):
            for tc in message["tool_calls"]:
                try:
                    args = json.loads(tc["function"]["arguments"])
                except (json.JSONDecodeError, KeyError):
                    args = {}
                tool_calls.append(
                    {
                        "name": tc["function"]["name"],
                        "arguments": args,
                        "_raw": tc,  # 保留原始格式供回灌用
                    }
                )
        else:
            content = message.get("content") or ""
            raw_json_objs = _extract_json_objects(content)
            for obj in raw_json_objs:
                tool_calls.append(
                    {
                        "name": obj["name"],
                        "arguments": obj.get("arguments", {}),
                    }
                )
        return tool_calls, raw_json_objs

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
        tool_map, allowed_args = _create_fresh_tool_context(test_case.get("session_context"))
        base_url = self.params["base_url"]
        model = self.params["model"]
        temperature = self.params.get("temperature", 0.0)
        url = (
            f"{base_url}/chat/completions"
            if not base_url.endswith("/chat/completions")
            else base_url
        )

        sampling_overrides = {}
        for key in ("repeat_penalty", "min_p", "top_p", "top_k", "presence_penalty"):
            if key in self.params:
                sampling_overrides[key] = self.params[key]

        messages = [{"role": "system", "content": self._system_prompt}]
        messages.extend(self._priming)
        messages.extend(
            _inject_session_context(test_case["messages"], test_case.get("session_context"))
        )

        all_tool_calls = []
        all_exec_results = []  # Response Template 用
        total_tokens = 0
        total_prompt_tokens = 0
        total_completion_tokens = 0
        actual_model = ""
        response_text = ""
        raw_responses = []  # 記錄每步原始 LLM 輸出（debug 用）

        enable_thinking = self.params.get("enable_thinking", False)

        client = self._get_client(timeout)
        for _step in range(self.MAX_TOOL_STEPS):
            send_messages = list(messages)
            if enable_thinking:
                send_messages.append({"role": "assistant", "content": "<think>\n", "prefix": True})
            elif self.params.get("force_no_think", False):
                # Qwen3.5 預設 think，需主動注入空 think block 跳過
                send_messages.append(
                    {"role": "assistant", "content": "<think>\n</think>\n", "prefix": True}
                )

            payload = {
                "model": model,
                "messages": send_messages,
                "temperature": temperature,
                "tools": self._tools_schema,
                **sampling_overrides,
            }

            logger.debug(
                "LLM request step=%d | model=%s | messages=%d", _step, model, len(messages)
            )

            resp = client.post(url, json=payload)
            if resp.status_code != 200:
                logger.error("LLM API 回傳 %d: %s", resp.status_code, resp.text[:500])
            resp.raise_for_status()
            data = resp.json()

            usage = data.get("usage", {})
            total_tokens += usage.get("total_tokens", 0)
            total_prompt_tokens += usage.get("prompt_tokens", 0)
            total_completion_tokens += usage.get("completion_tokens", 0)
            if not actual_model:
                actual_model = data.get("model", "")

            message = data["choices"][0]["message"]
            step_tool_calls, raw_objs = self._parse_tool_calls(message)
            raw_responses.append(
                {
                    "step": _step,
                    "content": message.get("content"),
                    "tool_calls": [tc["function"]["name"] for tc in message.get("tool_calls", [])],
                }
            )

            if not step_tool_calls:
                raw_content = message.get("content") or ""
                # 如果上一步有 prefill "好，"，補到回覆前面
                if _step > 0 and raw_content:
                    raw_content = "好，" + raw_content
                response_text = _clean_content(raw_content, [])
                # Response Template：ok:true 後用 code 構建回覆
                response_text = _apply_response_template(
                    response_text, all_tool_calls, all_exec_results
                )
                break

            all_tool_calls.extend(
                {"name": tc["name"], "arguments": tc["arguments"]} for tc in step_tool_calls
            )
            response_text = _clean_content(message.get("content"), raw_objs)

            # tool_calls 時 content 設 None（對齊 priming 格式，避免 model 看到自己的錯誤文字後延伸）
            assistant_msg = {"role": "assistant", "content": None}
            if message.get("tool_calls"):
                assistant_msg["tool_calls"] = message["tool_calls"]
            messages.append(assistant_msg)

            all_ok = True
            for tc in step_tool_calls:
                exec_result = _execute_tool(tool_map, allowed_args, tc["name"], tc["arguments"])
                all_exec_results.append(exec_result)
                if not exec_result.get("ok"):
                    all_ok = False
                # 對齊 production（llm_tool_caller.py）：用 role=tool + tool_call_id
                tool_call_id = tc.get("_raw", {}).get("id", f"toolcall_{_step}")
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "content": json.dumps(exec_result, ensure_ascii=False),
                    }
                )

            # ok:true 時 assistant prefill 引導正確回覆格式
            if all_ok:
                messages.append({"role": "assistant", "content": "好，", "prefix": True})

        if actual_model and actual_model != model:
            logger.warning(
                "模型不符！請求 %s → 實際 %s（LM Studio 可能 fallback）", model, actual_model
            )

        return {
            "response": response_text,
            "raw_responses": raw_responses,
            "tool_calls": all_tool_calls,
            "actual_model": actual_model,
            "tokens": total_tokens,
            "prompt_tokens": total_prompt_tokens,
            "completion_tokens": total_completion_tokens,
        }


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
            self._system_prompt, self._tools_schema = _load_static_context()
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
        tool_map, allowed_args = _create_fresh_tool_context(test_case.get("session_context"))
        base_url = self.params["base_url"]
        temperature = self.params.get("temperature", 0.0)

        sampling_overrides = {}
        for key in ("repeat_penalty", "min_p", "top_p", "top_k", "presence_penalty"):
            if key in self.params:
                sampling_overrides[key] = self.params[key]

        messages = [{"role": "system", "content": self._system_prompt}]
        messages.extend(self._priming)
        messages.extend(
            _inject_session_context(test_case["messages"], test_case.get("session_context"))
        )

        all_tool_calls = []
        total_tokens = 0
        total_prompt_tokens = 0
        total_completion_tokens = 0
        response_text = ""

        url = f"{base_url}/completion"

        client = self._get_client(timeout)
        for _step in range(self.MAX_TOOL_STEPS):
            prompt = self._renderer.render_prompt(
                messages,
                self._tools_schema,
                enable_thinking=False,
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

            total_prompt_tokens += data.get("tokens_evaluated", 0)
            total_completion_tokens += data.get("tokens_predicted", 0)
            total_tokens += data.get("tokens_evaluated", 0) + data.get("tokens_predicted", 0)

            content = data.get("content", "")

            raw_objs = _extract_json_objects(content)
            step_tool_calls = [
                {"name": obj["name"], "arguments": obj.get("arguments", {})} for obj in raw_objs
            ]

            if not step_tool_calls:
                response_text = _clean_content(content)
                break

            all_tool_calls.extend(step_tool_calls)
            response_text = _clean_content(content, raw_objs)

            messages.append({"role": "assistant", "content": content})

            for tc in step_tool_calls:
                exec_result = _execute_tool(tool_map, allowed_args, tc["name"], tc["arguments"])
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


class TextTagAdapter(BaseLLMAdapter):
    """Text Tag adapter — 不送 tools 參數，從 LLM 文字輸出解析 [ADD:...] / [QUERY:...] tags。

    與 OpenAICompatibleAdapter 的差異：
    - 不帶 tools 欄位（純文字模式）
    - MAX_TOOL_STEPS=1（模型一次輸出所有 tags，無多輪 tool loop）
    - 解析完 tags 後轉換為標準 tool_calls 格式，相容既有 scoring 邏輯
    """

    MAX_TOOL_STEPS = 1

    def __init__(self, params: dict):
        super().__init__(params)
        self._system_prompt = None
        self._priming = None
        self._client: httpx.Client | None = None

    def _ensure_static_context(self):
        """懶載入靜態 context（system prompt、priming、可選 grammar）"""
        if self._system_prompt is None:
            # 只需要 system_prompt；tools_schema 不送給 LLM
            from src.dm.system_prompts import build_system_prompt

            self._system_prompt = build_system_prompt()
            self._priming = _load_priming_messages()
            # use_grammar=True 時懶載入 GBNF（grammar-constrained decoding）
            self._grammar = None
            if self.params.get("use_grammar", False):
                from src.dm.grammar_builder import build_grammar

                self._grammar = build_grammar()

    def _get_client(self, timeout: float) -> httpx.Client:
        if self._client is None or self._client.is_closed:
            self._client = httpx.Client(timeout=timeout)
        return self._client

    def close(self):
        if self._client is not None and not self._client.is_closed:
            self._client.close()

    def _parse_text_tags(self, text: str) -> tuple[list[dict], str]:
        """從 text 中解析 [ADD:...] / [QUERY:...] tags，回傳 (tool_calls, cleaned_text)"""
        tool_calls = []

        # 解析 [ADD:品項名|key=value|...]
        for match in _ADD_RE.finditer(text):
            content = match.group(1)
            parts = content.split("|")
            name = parts[0].strip()
            args: dict = {"name": name}
            for part in parts[1:]:
                if "=" in part:
                    k, v = part.split("=", 1)
                    k, v = k.strip(), v.strip()
                    if k == "qty":
                        try:
                            args["quantity"] = int(v)
                        except ValueError:
                            pass
                    elif k in ("rice", "size", "temp", "flavor"):
                        args[k] = v
                    elif k in ("spicy", "extra_egg"):
                        args[k] = v.lower() == "true"
            tool_calls.append({"name": "add_item", "arguments": args})

        # 解析 [QUERY:category] 或 [QUERY]
        for match in _QUERY_RE.finditer(text):
            category = match.group(1)
            args = {}
            if category and category.strip():
                args["category"] = category.strip()
            tool_calls.append({"name": "query_menu", "arguments": args})

        # 移除所有 tags
        cleaned = _ADD_RE.sub("", text)
        cleaned = _QUERY_RE.sub("", cleaned).strip()

        return tool_calls, cleaned

    def run(self, test_case: dict, timeout: float = 60) -> dict:
        self._ensure_static_context()
        tool_map, allowed_args = _create_fresh_tool_context(test_case.get("session_context"))
        base_url = self.params["base_url"]
        model = self.params["model"]
        temperature = self.params.get("temperature", 0.0)
        url = (
            f"{base_url}/chat/completions"
            if not base_url.endswith("/chat/completions")
            else base_url
        )

        sampling_overrides = {}
        for key in ("repeat_penalty", "min_p", "top_p", "top_k", "presence_penalty"):
            if key in self.params:
                sampling_overrides[key] = self.params[key]

        messages = [{"role": "system", "content": self._system_prompt}]
        messages.extend(self._priming)
        messages.extend(
            _inject_session_context(test_case["messages"], test_case.get("session_context"))
        )

        # force_no_think：Qwen3.5 預設啟動 thinking，文字 tag 模式不需要
        if self.params.get("force_no_think", False):
            messages.append({"role": "assistant", "content": "<think>\n</think>\n", "prefix": True})

        # 純文字模式 — 不帶 tools 參數
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            **sampling_overrides,
        }
        if self._grammar is not None:
            payload["grammar"] = self._grammar

        logger.debug("TextTag request | model=%s | messages=%d", model, len(messages))

        client = self._get_client(timeout)
        resp = client.post(url, json=payload)
        if resp.status_code != 200:
            logger.error("LLM API 回傳 %d: %s", resp.status_code, resp.text[:500])
        resp.raise_for_status()
        data = resp.json()

        usage = data.get("usage", {})
        total_tokens = usage.get("total_tokens", 0)
        total_prompt_tokens = usage.get("prompt_tokens", 0)
        total_completion_tokens = usage.get("completion_tokens", 0)
        actual_model = data.get("model", "")

        message = data["choices"][0]["message"]
        raw_content = message.get("content") or ""

        # 清理 thinking block
        raw_content = re.sub(r"<think>.*?</think>", "", raw_content, flags=re.DOTALL).strip()

        # 解析 text tags → tool_calls
        tool_calls, cleaned_text = self._parse_text_tags(raw_content)

        # 執行 tools
        all_exec_results = []
        for tc in tool_calls:
            exec_result = _execute_tool(tool_map, allowed_args, tc["name"], tc["arguments"])
            all_exec_results.append(exec_result)
            if not exec_result.get("ok"):
                logger.debug(
                    "TextTag tool 執行失敗: %s → %s", tc["name"], exec_result.get("message")
                )

        # Response Template
        response_text = _apply_response_template(cleaned_text, tool_calls, all_exec_results)

        if actual_model and actual_model != model:
            logger.warning(
                "模型不符！請求 %s → 實際 %s（LM Studio 可能 fallback）", model, actual_model
            )

        return {
            "response": response_text,
            "raw_responses": [{"step": 0, "content": raw_content, "tool_calls": []}],
            "tool_calls": tool_calls,
            "actual_model": actual_model,
            "tokens": total_tokens,
            "prompt_tokens": total_prompt_tokens,
            "completion_tokens": total_completion_tokens,
        }


class GeminiTextTagAdapter(TextTagAdapter):
    """Gemini API adapter — text tag mode，繼承 TextTagAdapter 的 tag 解析邏輯。

    差異：HTTP 請求打 Gemini REST API（非 OpenAI 格式），
    回應格式轉換後共用 _parse_text_tags / _execute_tool / _apply_response_template。
    """

    GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"

    def __init__(self, params: dict):
        super().__init__(params)
        self._api_key = params.get("api_key") or os.environ.get(
            params.get("api_key_env", "GEMINI_API_KEY"), ""
        )
        if not self._api_key:
            raise ValueError("Gemini API key 未設定（params.api_key 或 env GEMINI_API_KEY）")

    def _messages_to_gemini(self, messages: list[dict]) -> tuple[str, list[dict]]:
        """OpenAI messages 格式 → Gemini contents 格式，回傳 (system_instruction, contents)"""
        system_parts = []
        contents = []
        for msg in messages:
            role = msg["role"]
            text = msg.get("content", "")
            if role == "system":
                system_parts.append(text)
            elif role == "user":
                contents.append({"role": "user", "parts": [{"text": text}]})
            elif role == "assistant":
                contents.append({"role": "model", "parts": [{"text": text}]})
        return "\n\n".join(system_parts), contents

    def run(self, test_case: dict, timeout: float = 60) -> dict:
        self._ensure_static_context()
        tool_map, allowed_args = _create_fresh_tool_context(test_case.get("session_context"))
        model = self.params.get("model", "gemini-2.5-flash")
        temperature = self.params.get("temperature", 0.2)

        messages = [{"role": "system", "content": self._system_prompt}]
        messages.extend(self._priming)
        messages.extend(
            _inject_session_context(test_case["messages"], test_case.get("session_context"))
        )

        system_instruction, contents = self._messages_to_gemini(messages)

        url = f"{self.GEMINI_BASE}/models/{model}:generateContent"
        payload = {
            "contents": contents,
            "systemInstruction": {"parts": [{"text": system_instruction}]},
            "generationConfig": {
                "temperature": temperature,
                "thinkingConfig": {"thinkingBudget": 0},
            },
        }

        logger.debug("Gemini request | model=%s | contents=%d", model, len(contents))

        client = self._get_client(timeout)
        headers = {"X-goog-api-key": self._api_key}

        # 429 rate limit retry（偵測日限 vs 分鐘限）
        max_retries = 6
        for attempt in range(max_retries):
            resp = client.post(url, json=payload, headers=headers)
            if resp.status_code != 429:
                break
            # 解析 quota 類型 — 日限耗盡直接 fail，不浪費 retry
            try:
                err_data = resp.json()
            except ValueError:
                logger.warning("Gemini 429 但回傳非 JSON: %s", resp.text[:200])
                err_data = {}
            quota_ids = [
                v.get("quotaId", "")
                for d in err_data.get("error", {}).get("details", [])
                for v in d.get("violations", [])
            ]
            daily_quota = next((q for q in quota_ids if "PerDay" in q), None)
            if daily_quota:
                raise RuntimeError(
                    f"Gemini 日限額度耗盡（{daily_quota}），請等待重置或升級付費方案"
                )
            if quota_ids:
                logger.debug("Gemini 429 quotaIds: %s", quota_ids)
            wait = min(30, 10 * (attempt + 1))
            logger.warning(
                "Gemini 429 rate limit, retry in %ds (%d/%d)", wait, attempt + 1, max_retries
            )
            time.sleep(wait)

        if resp.status_code != 200:
            logger.error("Gemini API 回傳 %d: %s", resp.status_code, resp.text[:500])
        resp.raise_for_status()
        data = resp.json()

        # 解析 Gemini 回應
        candidate = data.get("candidates", [{}])[0]
        parts = candidate.get("content", {}).get("parts", [])
        raw_content = "".join(p.get("text", "") for p in parts)

        usage = data.get("usageMetadata", {})
        total_prompt_tokens = usage.get("promptTokenCount", 0)
        total_completion_tokens = usage.get("candidatesTokenCount", 0)
        total_tokens = usage.get("totalTokenCount", 0)
        actual_model = data.get("modelVersion", model)

        # 解析 text tags → tool_calls（繼承自 TextTagAdapter）
        tool_calls, cleaned_text = self._parse_text_tags(raw_content)

        # 執行 tools
        all_exec_results = []
        for tc in tool_calls:
            exec_result = _execute_tool(tool_map, allowed_args, tc["name"], tc["arguments"])
            all_exec_results.append(exec_result)
            if not exec_result.get("ok"):
                logger.debug(
                    "Gemini tool 執行失敗: %s → %s", tc["name"], exec_result.get("message")
                )

        response_text = _apply_response_template(cleaned_text, tool_calls, all_exec_results)

        return {
            "response": response_text,
            "raw_responses": [{"step": 0, "content": raw_content, "tool_calls": []}],
            "tool_calls": tool_calls,
            "actual_model": actual_model,
            "tokens": total_tokens,
            "prompt_tokens": total_prompt_tokens,
            "completion_tokens": total_completion_tokens,
        }


REGISTRY = {
    "openai_compatible": OpenAICompatibleAdapter,
    "raw_completion": RawCompletionAdapter,
    "text_tag": TextTagAdapter,
    "gemini_text_tag": GeminiTextTagAdapter,
}


def create_llm_adapter(adapter_name: str, params: dict) -> BaseLLMAdapter:
    cls = REGISTRY.get(adapter_name)
    if cls is None:
        raise ValueError(f"未知的 LLM adapter: {adapter_name}，可用: {list(REGISTRY.keys())}")
    return cls(params)
