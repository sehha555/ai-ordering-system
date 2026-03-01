"""
Few-shot priming messages — 讓本地 LLM 學會使用 tool_calls 格式。

根因：LM Studio + Qwen3/2.5 在 tool_choice=auto 時，
模型不知道該用 tool_calls 欄位回覆。
注入一段示範對話後，模型就能正確判斷何時 call tool、何時用文字追問。

目前狀態：priming 暫時清空，改由 system prompt CoT 引導。
helper 函數（_tc / _tool_resp）保留供未來重新啟用使用。

注意：tool response 使用 role:user + <tool_result> tag，
避免觸發 LM Studio tools middleware 慢路徑（4s→42s）。
"""

import json


def _tc(call_id: str, name: str, args: dict) -> list[dict]:
    """構建 tool_calls 格式"""
    return [{
        "id": call_id,
        "type": "function",
        "function": {
            "name": name,
            "arguments": json.dumps(args, ensure_ascii=False),
        },
    }]


def _tool_resp(call_id: str, result: dict) -> dict:
    """構建 tool response（role:user + <tool_result> tag，避免 LM Studio middleware 慢路徑）"""
    return {
        "role": "user",
        "content": f"<tool_result>\n{json.dumps(result, ensure_ascii=False)}\n</tool_result>",
    }


def get_priming_messages() -> list[dict]:
    """Few-shot priming 暫時清空，改由 system prompt CoT 引導。"""
    return []
