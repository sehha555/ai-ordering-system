# src/services/llm_service.py
"""
LLM Service - 負責與語言模型互動
(新增 Tool Calling 自動執行/回餵)
"""

from __future__ import annotations

import os
import re
import json
from typing import Any, Dict, List, Optional

from openai import OpenAI

# 你的菜單工具（你已生成）
from src.tools import menu_tool


class LLMService:
    """LLM 服務類別"""

    def __init__(self):
        """初始化 LLM 服務"""
        self.use_mock = os.getenv("USE_MOCK", "false").lower() == "true"

        if not self.use_mock:
            self.client = OpenAI(
                base_url=os.getenv("LM_STUDIO_URL", "http://127.0.0.1:1234/v1"),
                api_key=os.getenv("LM_STUDIO_API_KEY", "lm-studio"),
            )
            self.model = os.getenv("LM_STUDIO_MODEL", "qwen2.5-14b-instruct-1m")

        # Tool calling 安全上限（避免模型一直 call tool）
        self.max_tool_rounds = int(os.getenv("MAX_TOOL_ROUNDS", "5"))

    def _strip_think(self, content: str) -> str:
        """保留你原本的 think 過濾邏輯"""
        if not content:
            return content

        content = content.strip()
        content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()

        if "<think>" in content:
            parts = content.split("<think>")
            content = parts[0].strip()

        return content

    def _dispatch_tool_call(self, name: str, args: Dict[str, Any]) -> Any:
        """
        把工具名稱對應到 menu_tool 內的函式
        你 menu_tool.py 已提供這些函式：
        - get_menu_categories
        - get_items_by_category
        - get_item_detail
        - list_flavors_by_type
        - list_types_by_flavor
        - find_menu_items
        - suggest_items_for_utterance
        """
        fn = getattr(menu_tool, name, None)
        if fn is None:
            raise ValueError(f"Unknown tool: {name}")

        return fn(**args) if args else fn()

    def call_llm(
        self,
        user_message: str,
        system_prompt: Optional[str] = None,
        use_tools: bool = True,
    ) -> str:
        """
        呼叫 LLM 取得回應
        - use_tools=True：會帶入 menu_tool 的 tools schema，並自動處理 tool_calls
        """
        if self.use_mock:
            return "【MOCK 模式】歡迎光臨源飯糰,請問要點什麼?"

        try:
            messages: List[Dict[str, Any]] = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": user_message})

            tools = menu_tool.get_openai_tools_schema() if use_tools else None

            # ====== Tool calling loop ======
            for _round in range(self.max_tool_rounds):
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=0.3,
                    max_tokens=800,
                    tools=tools,
                    tool_choice="auto" if tools else "none",
                    extra_body={"stop": ["<|im_end|>"]},
                )

                msg = response.choices[0].message

                # 1) 如果模型要呼叫工具
                tool_calls = getattr(msg, "tool_calls", None)
                if tool_calls:
                    # 把 assistant 的 tool_calls 訊息也加進 messages（OpenAI pattern）
                    messages.append(
                        {
                            "role": "assistant",
                            "content": msg.content or "",
                            "tool_calls": [
                                {
                                    "id": tc.id,
                                    "type": tc.type,
                                    "function": {
                                        "name": tc.function.name,
                                        "arguments": tc.function.arguments,
                                    },
                                }
                                for tc in tool_calls
                            ],
                        }
                    )

                    # 逐一執行 tool
                    for tc in tool_calls:
                        tool_name = tc.function.name
                        raw_args = tc.function.arguments or "{}"

                        try:
                            args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
                        except Exception:
                            # arguments 解析失敗就當空
                            args = {}

                        tool_result = self._dispatch_tool_call(tool_name, args)

                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tc.id,
                                "content": json.dumps(tool_result, ensure_ascii=False),
                            }
                        )

                    # 繼續下一輪，讓模型讀 tool 結果並生成最終回答
                    continue

                # 2) 沒有 tool_calls → 代表已經是最終回答
                content = (msg.content or "").strip()
                content = self._strip_think(content)

                if not content:
                    return "不好意思，請再說一次？ (模型思考中斷)"

                return content

            # 超過 max_tool_rounds 仍未產生最終回答
            return "不好意思，我這邊確認菜單資訊卡住了，請再說一次或換個說法。"

        except Exception as e:
            raise Exception(f"LLM 呼叫失敗: {e}")



