"""
Few-shot priming messages — 讓本地 LLM 學會使用 tool_calls 格式。

根因：LM Studio + Qwen3/2.5 在 tool_choice=auto 時，
模型不知道該用 tool_calls 欄位回覆。
注入一段示範對話後，模型就能正確判斷何時 call tool、何時用文字追問。

注意：tool response 使用 role:user + <tool_result> tag，
避免觸發 LM Studio tools middleware 慢路徑（4s→42s）。
"""

import json

# 統一 tag 格式，benchmark adapter 也引用此常數
TOOL_RESULT_TAG = "tool_result"


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


def format_tool_result(result: dict) -> str:
    """將工具執行結果格式化為 <tool_result> 文字（priming + benchmark 共用）"""
    return f"<{TOOL_RESULT_TAG}>\n{json.dumps(result, ensure_ascii=False)}\n</{TOOL_RESULT_TAG}>"


def _tool_resp(call_id: str, result: dict) -> dict:
    """構建 tool response（role:user + <tool_result> tag，繞過 server middleware 慢路徑）"""
    return {
        "role": "user",
        "content": format_tool_result(result),
    }


def get_priming_messages() -> list[dict]:
    """精選 priming 示範，搭配 system prompt CoT 引導模型行為。

    12 個 demo 覆蓋關鍵行為模式（排序：基礎→追問→複雜→結帳→邊界）：
    1. 點心直接加（蘿蔔糕加蛋，易混淆品項）
    2. 飲料缺規格 → 追問
    3. 飯糰缺米種 → 追問
    4. 載體缺 → 追問 → 補齊後 call
    5. 別名解析 → 直接 call
    6. 套餐 → call → ok:false → 轉述追問
    7. 多品項全齊 → 連續 call
    8. 查詢菜單 → query_menu
    9. 多品項部分缺 → call 齊全的 + 追問缺的
    10. 饅頭缺口味 → 追問
    11. 結帳完整流程 → finalize_order
    12. 邊界 — 購物車沒有該品項 → 不 call tool（最後，強化保護行為）
    """
    msgs: list[dict] = []

    # Demo 1: 點心直接加（snack 無必填，直接 call；用蘿蔔糕加蛋示範易混淆品項）
    msgs.append({"role": "user", "content": "一份蘿蔔糕加蛋"})
    msgs.append({
        "role": "assistant",
        "content": None,
        "tool_calls": _tc("c1", "add_to_cart", {
            "item_type": "snack", "flavor": "蘿蔔糕加蛋",
        }),
    })
    msgs.append(_tool_resp("c1", {"ok": True, "message": "已加入：蘿蔔糕加蛋"}))
    msgs.append({"role": "assistant", "content": "好，一份蘿蔔糕加蛋～還要什麼？"})

    # Demo 2: 飲料缺規格 → 追問（不 call tool）
    msgs.append({"role": "user", "content": "一杯紅茶"})
    msgs.append({"role": "assistant", "content": "大杯還是中杯？冰的還是溫的？"})

    # Demo 3: 飯糰缺米種 → 追問（不 call tool）
    msgs.append({"role": "user", "content": "一個鮪魚飯糰"})
    msgs.append({"role": "assistant", "content": "紫米白米還是混米？"})

    # Demo 4: 載體缺 → 追問 → 補齊後 call
    msgs.append({"role": "user", "content": "一個起司蛋"})
    msgs.append({"role": "assistant", "content": "吐司還是漢堡？"})
    msgs.append({"role": "user", "content": "吐司"})
    msgs.append({
        "role": "assistant",
        "content": None,
        "tool_calls": _tc("c4", "add_to_cart", {
            "item_type": "carrier", "carrier": "吐司", "flavor": "起司蛋",
        }),
    })
    msgs.append(_tool_resp("c4", {"ok": True, "message": "已加入：起司蛋吐司"}))
    msgs.append({"role": "assistant", "content": "好，一個起司蛋吐司～還要什麼？"})

    # Demo 5: 別名解析 → 直接 call（大冰奶 = 大杯冰純鮮奶茶）
    msgs.append({"role": "user", "content": "大冰奶"})
    msgs.append({
        "role": "assistant",
        "content": None,
        "tool_calls": _tc("c5", "add_to_cart", {
            "item_type": "drink", "flavor": "純鮮奶茶", "size": "大杯", "temp": "冰",
        }),
    })
    msgs.append(_tool_resp("c5", {"ok": True, "message": "已加入：純鮮奶茶(大/冰)"}))
    msgs.append({"role": "assistant", "content": "好，一杯大冰純鮮奶茶～還要什麼？"})

    # Demo 6: 套餐 → call → ok:false → 轉述追問
    msgs.append({"role": "user", "content": "一個套餐一"})
    msgs.append({
        "role": "assistant",
        "content": None,
        "tool_calls": _tc("c6", "add_to_cart", {
            "item_type": "combo", "combo_name": "套餐一",
        }),
    })
    msgs.append(_tool_resp("c6", {"ok": False, "message": "缺飲料溫度，冰的還是溫的？"}))
    msgs.append({"role": "assistant", "content": "飲料冰的還是溫的？"})

    # Demo 7: 多品項連續 call（齊全的先 call，每品項各 call 一次）
    msgs.append({"role": "user", "content": "兩個玉米蛋餅 一個薯餅"})
    msgs.append({
        "role": "assistant",
        "content": None,
        "tool_calls": _tc("c7a", "add_to_cart", {
            "item_type": "egg_pancake", "flavor": "玉米蛋餅", "quantity": 2,
        }),
    })
    msgs.append(_tool_resp("c7a", {"ok": True, "message": "已加入：玉米蛋餅 x2"}))
    msgs.append({
        "role": "assistant",
        "content": None,
        "tool_calls": _tc("c7b", "add_to_cart", {
            "item_type": "snack", "flavor": "薯餅",
        }),
    })
    msgs.append(_tool_resp("c7b", {"ok": True, "message": "已加入：薯餅"}))
    msgs.append({"role": "assistant", "content": "好，兩個玉米蛋餅加一個薯餅～還要什麼？"})

    # Demo 8: 查詢菜單（飲料有哪些 → query_menu）
    msgs.append({"role": "user", "content": "有什麼飲料"})
    msgs.append({
        "role": "assistant",
        "content": None,
        "tool_calls": _tc("c8", "query_menu", {"category": "飲品"}),
    })
    msgs.append(_tool_resp("c8", {"ok": True, "message": "飲品：紅茶、奶茶、豆漿、純鮮奶茶..."}))
    msgs.append({"role": "assistant", "content": "飲料有紅茶、奶茶、豆漿、純鮮奶茶等，要來一杯嗎？"})

    # Demo 9: 多品項部分缺資訊 — call 齊全的，追問缺的
    msgs.append({"role": "user", "content": "兩個玉米蛋餅 一個起司蛋"})
    msgs.append({
        "role": "assistant",
        "content": None,
        "tool_calls": _tc("c9", "add_to_cart", {
            "item_type": "egg_pancake", "flavor": "玉米蛋餅", "quantity": 2,
        }),
    })
    msgs.append(_tool_resp("c9", {"ok": True, "message": "已加入：玉米蛋餅 x2"}))
    msgs.append({"role": "assistant", "content": "好，起司蛋吐司還是漢堡？"})

    # Demo 10: 饅頭缺口味 → 追問（不 call tool）
    msgs.append({"role": "user", "content": "一個饅頭夾蛋"})
    msgs.append({"role": "assistant", "content": "黑糖、白饅頭還是花捲？"})

    # Demo 11: 結帳完整流程 → finalize_order
    msgs.append({"role": "user", "content": "不用了 結帳"})
    msgs.append({"role": "assistant", "content": "內用還是外帶？"})
    msgs.append({"role": "user", "content": "外帶"})
    msgs.append({"role": "assistant", "content": "現金還是行動支付？"})
    msgs.append({"role": "user", "content": "現金"})
    msgs.append({
        "role": "assistant",
        "content": None,
        "tool_calls": _tc("c11", "finalize_order", {
            "dine_type": "外帶", "payment_method": "現金",
        }),
    })
    msgs.append(_tool_resp("c11", {"ok": True, "order_id": "A042"}))
    msgs.append({"role": "assistant", "content": "好，42 號～"})

    # Demo 12: 邊界 — 購物車沒有該品項，不 call tool 直接回覆（最後位置，近因效應強化保護行為）
    msgs.append({"role": "user", "content": "把蛋餅取消"})
    msgs.append({"role": "assistant", "content": "購物車裡沒有蛋餅喔，不用取消～還需要什麼？"})

    return msgs
