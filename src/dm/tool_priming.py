"""
Few-shot priming messages — 讓本地 LLM 學會使用 tool_calls 格式。

根因：LM Studio + Qwen3/2.5 在 tool_choice=auto 時，
模型不知道該用 tool_calls 欄位回覆。
注入一段示範對話後，模型就能正確判斷何時 call tool、何時用文字追問。

示範覆蓋三種行為：
1. 資訊齊全 → call add_to_cart
2. 缺資訊 → 用文字追問（不 call tool）
3. 結帳流程 → call finalize_order
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
    """構建 tool response"""
    return {
        "role": "tool",
        "tool_call_id": call_id,
        "content": json.dumps(result, ensure_ascii=False),
    }


def get_priming_messages() -> list[dict]:
    """返回 few-shot priming messages"""
    return [
        # 示範 1: 資訊齊全 → call tool
        {"role": "user", "content": "一個起司蛋餅"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": _tc("demo_1", "add_to_cart", {
                "item_type": "egg_pancake", "flavor": "起司",
            }),
        },
        _tool_resp("demo_1", {"ok": True, "message": "已添加 1 份 起司蛋餅", "cart_count": 1}),
        {"role": "assistant", "content": "好 還要嗎"},

        # 示範 2: 缺資訊 → 文字追問（不 call tool）
        {"role": "user", "content": "一杯紅茶"},
        {"role": "assistant", "content": "飲料冰的溫的 大杯中杯"},

        # 示範 3: 補齊後 → call tool
        {"role": "user", "content": "大冰"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": _tc("demo_2", "add_to_cart", {
                "item_type": "drink", "flavor": "紅茶", "size": "大杯", "temp": "冰",
            }),
        },
        _tool_resp("demo_2", {"ok": True, "message": "已添加 1 份 大杯冰紅茶", "cart_count": 2}),
        {"role": "assistant", "content": "好 還要嗎"},

        # 示範 4: 結帳流程
        {"role": "user", "content": "沒了"},
        {"role": "assistant", "content": "內用還是外帶"},
        {"role": "user", "content": "外帶"},
        {"role": "assistant", "content": "現金還是行動支付"},
        {"role": "user", "content": "現金"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": _tc("demo_3", "finalize_order", {
                "dine_type": "外帶", "payment_method": "現金",
            }),
        },
        _tool_resp("demo_3", {"ok": True, "order_number": 1, "total": 55}),
        {"role": "assistant", "content": "好 取餐號碼 1 號 總共 55 元"},
    ]
