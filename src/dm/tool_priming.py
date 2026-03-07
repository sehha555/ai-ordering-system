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
    """構建 tool response（role:tool + tool_call_id，對齊 production llm_tool_caller.py）"""
    return {
        "role": "tool",
        "tool_call_id": call_id,
        "content": json.dumps(result, ensure_ascii=False),
    }


def get_priming_messages() -> list[dict]:
    """精選 priming 示範，搭配 system prompt CoT 引導模型行為。

    6 個高質量 demo，品項全部與 test_scenarios.json 不重疊（防記憶化）：
    1. 飯糰完整 call — boolean spicy + flavor 不帶後綴（修 Pattern C 參數格式）
    2. 載體缺 → 追問 → 補齊後 call（培根蛋，避開 test 火腿蛋/起司蛋）
    3. 套餐數字別名 → call → ok:false → 追問（修 combo_alias + combo_missing_temp）
    4. 多品項部分缺 — add_carrier + add_drink 齊全先 call，奶茶缺規格追問
    5. 結帳完整流程 → finalize_order（Line Pay，與 test case 現金不重疊）
    6. 邊界 — 品項不在購物車 → 不 call tool（近因效應，修 cancel_nonexistent）
    """
    msgs: list[dict] = []

    # Demo 1: 飯糰完整 call — 示範 boolean spicy=false + flavor 只填口味名稱
    # 品項：鮭魚（test cases 沒有此品項），修正 Pattern C（riceball 參數格式錯誤）
    msgs.append({"role": "user", "content": "一個鮭魚飯糰 白米 不加辣"})
    msgs.append({
        "role": "assistant",
        "content": None,
        "tool_calls": _tc("c1", "add_riceball", {
            "flavor": "鮭魚", "rice": "白米", "spicy": False,
        }),
    })
    msgs.append(_tool_resp("c1", {"ok": True, "item_id": "rb_1", "message": "已加入 1份 白米鮭魚", "cart_count": 1}))
    msgs.append({"role": "assistant", "content": "好，白米鮭魚飯糰～還要什麼？"})

    # Demo 2: 載體缺 → 追問 → 補齊後 call（完整多輪循環）
    # 品項：培根蛋（test cases 用起司蛋/火腿蛋），覆蓋「缺必填→追問→補齊→call」
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
    msgs.append(_tool_resp("c2", {"ok": True, "item_id": "cr_1", "message": "已加入 1份 培根蛋吐司", "cart_count": 2}))
    msgs.append({"role": "assistant", "content": "好，培根蛋吐司～還要什麼？"})

    # Demo 3: 套餐數字別名 → call → ok:false → 追問
    # 品項：三號餐（test cases 用套餐一/四），同時示範別名解析 + ok:false 反饋循環
    msgs.append({"role": "user", "content": "一個三號餐"})
    msgs.append({
        "role": "assistant",
        "content": None,
        "tool_calls": _tc("c3", "add_combo", {
            "combo_name": "套餐三",
        }),
    })
    msgs.append(_tool_resp("c3", {"ok": False, "message": "缺飲料溫度，冰的還是溫的？"}))
    msgs.append({"role": "assistant", "content": "飲料要冰的還是溫的？"})

    # Demo 4: 多品項部分缺 — call 齊全的 + 追問缺的（含 add_drink 示範）
    # 品項：花生吐司 + 大冰十穀漿（齊全） + 奶茶（缺規格）
    # 教學：齊全先 call（含 add_drink），缺的用簡稱追問（中冰/中溫）
    msgs.append({"role": "user", "content": "一個花生吐司 一杯大冰十穀漿 一杯奶茶"})
    msgs.append({
        "role": "assistant",
        "content": None,
        "tool_calls": _tc("c4a", "add_carrier", {
            "carrier": "吐司", "flavor": "花生",
        }),
    })
    msgs.append(_tool_resp("c4a", {"ok": True, "item_id": "cr_3", "message": "已加入 1份 花生吐司", "cart_count": 3}))
    msgs.append({
        "role": "assistant",
        "content": None,
        "tool_calls": _tc("c4b", "add_drink", {
            "flavor": "十穀漿", "size": "大杯", "temp": "冰",
        }),
    })
    msgs.append(_tool_resp("c4b", {"ok": True, "item_id": "dk_1", "message": "已加入 1份 大杯冰十穀漿", "cart_count": 4}))
    msgs.append({"role": "assistant", "content": "好，奶茶要中冰還是中溫？"})

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
    msgs.append(_tool_resp("c5", {"ok": True, "order_id": "B023"}))
    msgs.append({"role": "assistant", "content": "好，23號～"})

    # Demo 6: 邊界 — 品項不在購物車 → 不 call tool（最後位置，近因效應強化保護行為）
    # 品項：奶茶（test cases 用蛋餅），行為模式相同但品項不重疊
    msgs.append({"role": "user", "content": "幫我把奶茶取消"})
    msgs.append({"role": "assistant", "content": "購物車裡沒有奶茶喔，不用取消～還需要什麼？"})

    return msgs
