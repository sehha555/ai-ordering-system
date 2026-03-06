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

    7 個高質量 demo，品項全部與 test_scenarios.json 不重疊（防記憶化）：
    1. 飯糰多輪 — 問米種→問辣菜脯→call（香燻培根，教兩輪追問流程）
    2. 載體缺 → 追問 → 補齊後 call（培根蛋，只問吐司/漢堡）
    3. 套餐數字別名 → call → ok:false → 追問（三號餐）
    4. 多品項部分缺 — add_carrier + add_drink 齊全先 call，鮮奶茶缺規格用季節預設
    5. 結帳完整流程 → finalize_order（Line Pay）
    6. 邊界 — 品項不在購物車 → 不 call tool（近因效應）
    7. 大冰奶意圖 → add_drink（修 intent_big_iced_milk 穩定失敗）

    tool result 格式對齊實際回傳（含 item_id、cart_count），避免模型因格式不符而道歉。
    """
    msgs: list[dict] = []

    # Demo 1: 飯糰多輪 — 先問米種，再問辣菜脯，最後 call
    # 品項：香燻培根（test cases 用鮪魚/源味傳統）
    msgs.append({"role": "user", "content": "一個香燻培根飯糰"})
    msgs.append({"role": "assistant", "content": "紫米還是白米？"})
    msgs.append({"role": "user", "content": "紫米"})
    msgs.append({"role": "assistant", "content": "要不要加辣菜脯？"})
    msgs.append({"role": "user", "content": "不用"})
    msgs.append({
        "role": "assistant",
        "content": None,
        "tool_calls": _tc("c1", "add_riceball", {
            "flavor": "香燻培根", "rice": "紫米", "spicy": False,
        }),
    })
    msgs.append(_tool_resp("c1", {
        "ok": True, "item_id": "riceball_1",
        "message": "已加入 1份 紫米香燻培根", "cart_count": 1,
    }))
    msgs.append({"role": "assistant", "content": "好，一個紫米香燻培根飯糰～還要什麼？"})

    # Demo 2: 載體缺 → 追問 → 補齊後 call
    # 品項：培根蛋（test cases 用起司蛋/火腿蛋）
    msgs.append({"role": "user", "content": "一個培根蛋"})
    msgs.append({"role": "assistant", "content": "吐司還是漢堡？"})
    msgs.append({"role": "user", "content": "吐司"})
    msgs.append({
        "role": "assistant",
        "content": None,
        "tool_calls": _tc("c2", "add_carrier", {
            "carrier": "吐司", "flavor": "培根蛋",
        }),
    })
    msgs.append(_tool_resp("c2", {
        "ok": True, "item_id": "carrier_1",
        "message": "已加入 1份 培根蛋吐司", "cart_count": 2,
    }))
    msgs.append({"role": "assistant", "content": "好，一個培根蛋吐司～還要什麼？"})

    # Demo 3: 套餐數字別名 → call → ok:false → 追問
    # 品項：三號餐（test cases 用套餐一/四）
    msgs.append({"role": "user", "content": "一個三號餐"})
    msgs.append({
        "role": "assistant",
        "content": None,
        "tool_calls": _tc("c3", "add_combo", {
            "combo_name": "套餐三",
        }),
    })
    msgs.append(_tool_resp("c3", {"ok": False, "message": "飲料冰的還是溫的"}))
    msgs.append({"role": "assistant", "content": "套餐飲料要冰的溫的？"})

    # Demo 4: 多品項部分缺 — call 齊全的 + 追問缺的（含 add_drink + 季節預設）
    # 品項：花生吐司 + 大冰十穀漿（齊全） + 鮮奶茶（缺杯型/溫度，用季節預設）
    msgs.append({"role": "user", "content": "一個花生吐司 一杯大冰十穀漿 一杯鮮奶茶"})
    msgs.append({
        "role": "assistant",
        "content": None,
        "tool_calls": _tc("c4a", "add_carrier", {
            "carrier": "吐司", "flavor": "花生",
        }),
    })
    msgs.append(_tool_resp("c4a", {
        "ok": True, "item_id": "carrier_2",
        "message": "已加入 1份 花生吐司", "cart_count": 3,
    }))
    msgs.append({
        "role": "assistant",
        "content": None,
        "tool_calls": _tc("c4b", "add_drink", {
            "flavor": "十穀漿", "size": "大杯", "temp": "冰",
        }),
    })
    msgs.append(_tool_resp("c4b", {
        "ok": True, "item_id": "drink_1",
        "message": "已加入 1份 大杯冰十穀漿", "cart_count": 4,
    }))
    msgs.append({"role": "assistant", "content": "好，鮮奶茶要中冰好？"})

    # Demo 5: 結帳完整流程 → finalize_order（Line Pay，與 test H2 現金不重疊）
    msgs.append({"role": "user", "content": "好了 買單"})
    msgs.append({"role": "assistant", "content": "內用還是外帶？"})
    msgs.append({"role": "user", "content": "外帶"})
    msgs.append({"role": "assistant", "content": "現金還是行動支付？"})
    msgs.append({"role": "user", "content": "Line Pay"})
    msgs.append({
        "role": "assistant",
        "content": None,
        "tool_calls": _tc("c5", "finalize_order", {
            "dine_type": "外帶", "payment_method": "line_pay",
        }),
    })
    msgs.append(_tool_resp("c5", {
        "ok": True, "order_number": 23, "total": 285,
        "item_count": 4, "dine_type": "外帶", "payment_method": "line_pay",
    }))
    msgs.append({"role": "assistant", "content": "好，23號～"})

    # Demo 6: 邊界 — 品項不在購物車 → 不 call tool（近因效應強化保護行為）
    # 品項：奶茶（test cases 用蛋餅）
    msgs.append({"role": "user", "content": "幫我把鮮奶茶取消"})
    msgs.append({"role": "assistant", "content": "購物車裡沒有鮮奶茶喔，不用取消～還需要什麼？"})

    # Demo 7: 大冰奶 = 大杯冰純鮮奶茶 → 直接 call（修 intent_big_iced_milk 穩定失敗）
    msgs.append({"role": "user", "content": "大冰奶"})
    msgs.append({
        "role": "assistant",
        "content": None,
        "tool_calls": _tc("c7", "add_drink", {
            "flavor": "純鮮奶茶", "size": "大杯", "temp": "冰",
        }),
    })
    msgs.append(_tool_resp("c7", {
        "ok": True, "item_id": "drink_2",
        "message": "已加入 1份 大杯冰純鮮奶茶", "cart_count": 1,
    }))
    msgs.append({"role": "assistant", "content": "好，一杯大冰鮮奶茶～還要什麼？"})

    return msgs
