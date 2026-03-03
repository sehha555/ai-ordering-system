"""
Qwen3 Chat Template 渲染器

用官方 Jinja2 template 將 messages + tools 渲染為 raw prompt 字串，
送 llama.cpp /completion endpoint，完全跳過 server 的 template 渲染。

設計：
- Template 從 Qwen3 tokenizer_config.json hardcode（避免依賴本地模型檔）
- render_prompt() 處理 priming 格式轉換（role:user + <tool_result> → role:tool）
- enable_thinking=False：抑制 <think> 區塊（對齊 system prompt /no_think）
"""

import json
import re

from jinja2 import BaseLoader, Environment

# Qwen3 官方 chat template（從 tokenizer_config.json 提取）
# 支援 tools、tool_calls、tool response、enable_thinking
QWEN3_CHAT_TEMPLATE = """\
{%- if tools %}
    {{- '<|im_start|>system\\n' }}
    {%- if messages[0].role == 'system' %}
        {{- messages[0].content + '\\n\\n' }}
    {%- endif %}
    {{- "# Tools\\n\\nYou may call one or more functions to assist with the user query.\\n\\nYou are provided with function signatures within <tools></tools> XML tags:\\n<tools>" }}
    {%- for tool in tools %}
        {{- "\\n" + tool | tojson }}
    {%- endfor %}
    {{- "\\n</tools>\\n\\nFor each function call, return a json object with function name and arguments within <tool_call></tool_call> XML tags:\\n<tool_call>\\n{\\"name\\": <function-name>, \\"arguments\\": <args-json-object>}\\n</tool_call>" }}
    {{- '\\n<|im_end|>\\n' }}
{%- else %}
    {%- if messages[0].role == 'system' %}
        {{- '<|im_start|>system\\n' + messages[0].content + '\\n<|im_end|>\\n' }}
    {%- endif %}
{%- endif %}
{%- set ns = namespace(multi_step_tool=true, last_query_index=messages|length - 1) %}
{%- for message in messages %}
    {%- if message.role == 'user' and message.content is string %}
        {%- set ns.last_query_index = loop.index0 %}
    {%- endif %}
{%- endfor %}
{%- for message in messages %}
    {%- if message.role == 'user' and message.content is string %}
        {%- if loop.index0 > 0 or not tools %}
            {{- '<|im_start|>user\\n' + message.content + '\\n<|im_end|>\\n' }}
        {%- endif %}
    {%- elif message.role == 'assistant' %}
        {%- set ns.multi_step_tool = false %}
        {%- if message.content is string or message.content is none %}
            {%- if message.tool_calls is defined and message.tool_calls %}
                {{- '<|im_start|>assistant\\n' }}
                {%- if message.content is string and message.content|length > 0 %}
                    {{- message.content }}
                {%- endif %}
                {%- for tool_call in message.tool_calls %}
                    {%- if tool_call.function %}
                        {{- '<tool_call>\\n{"name": "' + tool_call.function.name + '", "arguments": ' + tool_call.function.arguments + '}\\n</tool_call>\\n' }}
                    {%- endif %}
                {%- endfor %}
                {{- '<|im_end|>\\n' }}
            {%- else %}
                {%- if message.content is none %}
                    {{- '<|im_start|>assistant\\n<|im_end|>\\n' }}
                {%- else %}
                    {{- '<|im_start|>assistant\\n' + message.content + '\\n<|im_end|>\\n' }}
                {%- endif %}
            {%- endif %}
        {%- endif %}
    {%- elif message.role == 'tool' %}
        {%- set ns.multi_step_tool = true %}
        {{- '<|im_start|>user\\n<tool_response>\\n' + message.content + '\\n</tool_response>\\n<|im_end|>\\n' }}
    {%- endif %}
{%- endfor %}
{%- if ns.multi_step_tool %}
    {{- '<|im_start|>assistant\\n' }}
{%- else %}
    {{- '<|im_start|>assistant\\n' }}
    {%- if enable_thinking is defined and enable_thinking is true %}
        {{- '<think>\\n' }}
    {%- else %}
        {{- '<think>\\n\\n</think>\\n\\n' }}
    {%- endif %}
{%- endif %}"""

# <tool_result> tag 解析（priming 格式轉換用）
_TOOL_RESULT_RE = re.compile(
    r"<tool_result>\s*(.*?)\s*</tool_result>", re.DOTALL
)


class Qwen3TemplateRenderer:
    """Qwen3 chat template 渲染器"""

    def __init__(self):
        env = Environment(loader=BaseLoader(), keep_trailing_newline=True)
        self._template = env.from_string(QWEN3_CHAT_TEMPLATE)

    def render_prompt(
        self,
        messages: list[dict],
        tools_schema: list[dict] | None = None,
        enable_thinking: bool = False,
    ) -> str:
        """將 messages + tools 渲染為 raw prompt 字串

        Args:
            messages: OpenAI 格式 messages（會自動轉換 priming 的 tool_result 格式）
            tools_schema: function calling tools schema（傳入 template 渲染 <tools> 區塊）
            enable_thinking: 是否啟用 <think> 區塊（False = 抑制思考）

        Returns:
            完整的 raw prompt 字串，可直接送 /completion
        """
        converted = self._convert_messages(messages)

        # Jinja2 template 需要 message 物件有 attribute 存取（用 namespace 模擬）
        msg_objs = [_MessageProxy(m) for m in converted]

        return self._template.render(
            messages=msg_objs,
            tools=tools_schema or [],
            enable_thinking=enable_thinking,
        )

    @staticmethod
    def _convert_messages(messages: list[dict]) -> list[dict]:
        """轉換 priming 格式：role:user + <tool_result> → role:tool + plain JSON

        Priming 中的 tool response 格式：
            {"role": "user", "content": "<tool_result>\\n{...}\\n</tool_result>"}

        官方 template 需要的格式：
            {"role": "tool", "content": "{...}"}
        """
        result = []
        for msg in messages:
            if msg.get("role") == "user" and isinstance(msg.get("content"), str):
                match = _TOOL_RESULT_RE.search(msg["content"])
                if match:
                    # 轉換為 role:tool，content 為純 JSON 字串
                    result.append({
                        "role": "tool",
                        "content": match.group(1).strip(),
                    })
                    continue
            result.append(msg)
        return result


class _MessageProxy:
    """讓 dict 支援 Jinja2 template 的 attribute 存取（message.role, message.content 等）"""

    def __init__(self, data: dict):
        self._data = data
        # tool_calls 內的 function 也需要 attribute 存取
        if "tool_calls" in data and data["tool_calls"]:
            self.tool_calls = [_ToolCallProxy(tc) for tc in data["tool_calls"]]
        else:
            self.tool_calls = None

    def __getattr__(self, name):
        if name.startswith("_") or name == "tool_calls":
            raise AttributeError(name)
        return self._data.get(name)

    def __contains__(self, key):
        return key in self._data

    def __getitem__(self, key):
        return self._data[key]


class _ToolCallProxy:
    """tool_call dict 的 attribute 代理"""

    def __init__(self, data: dict):
        self._data = data
        func = data.get("function", {})
        self.function = _FunctionProxy(func) if func else None

    def __getattr__(self, name):
        if name.startswith("_") or name == "function":
            raise AttributeError(name)
        return self._data.get(name)


class _FunctionProxy:
    """function dict 的 attribute 代理"""

    def __init__(self, data: dict):
        self.name = data.get("name", "")
        # arguments 必須是字串（JSON），template 直接嵌入
        args = data.get("arguments", "{}")
        if isinstance(args, dict):
            self.arguments = json.dumps(args, ensure_ascii=False)
        else:
            self.arguments = args
