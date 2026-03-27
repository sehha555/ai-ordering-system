"""
Few-shot priming messages — 讓本地 LLM 學會使用 tool_calls 格式。

根因：LM Studio + Qwen3/2.5 在 tool_choice=auto 時，
模型不知道該用 tool_calls 欄位回覆。
注入一段示範對話後，模型就能正確判斷何時 call tool、何時用文字追問。

注意：tool response 使用 role:tool + tool_call_id，
對齊 production llm_tool_caller.py。
"""

import json

# 統一 tag 格式，benchmark adapter 也引用此常數
TOOL_RESULT_TAG = "tool_result"

# LLM 回覆中的結帳標記（voice_router 攔截用）
CHECKOUT_TAG = "[CHECKOUT]"


def _tc(call_id: str, name: str, args: dict) -> list[dict]:
    """構建 tool_calls 格式"""
    return [
        {
            "id": call_id,
            "type": "function",
            "function": {
                "name": name,
                "arguments": json.dumps(args, ensure_ascii=False),
            },
        }
    ]


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

    9 個高質量 demo，品項全部與 test_scenarios.json 不重疊（防記憶化）。
    改用 add_item 統一入口：
    1. 飯糰完整 call — name=完整飯糰名, rice 必填
    2. 載體直接 call — name=完整載體品項名（吐司/漢堡/饅頭），後端自動路由
    3. 套餐帶溫度直接 call — add_item(name="套餐一", temp="冰")
    4. 俗稱飲料大冰奶 → add_item(name="純鮮奶茶", size="大杯", temp="冰")
    5. 多品項部分缺 — 齊全的先 call，飲料缺規格追問
    6. 結帳完整流程 → [CHECKOUT] tag
    7. 菜單查詢 → call query_menu(category="飲品") → 列舉回覆
    8. 套餐缺溫度 → add_item(name="套餐三") → ok:false → 追問
    9. 取消品項用 [REMOVE] tag

    注意：超過 9 demo 可能觸發 few-shot collapse（實測 11 demo 導致 riceball/carrier/combo 退化）
    """
    msgs: list[dict] = []

    # Demo 1: 飯糰完整 call — name 用菜單全名，rice 必填
    # 品項：鮪魚飯糰白米（test cases 常用鮪魚，但此 demo 覆蓋「完整全名 + rice」格式）
    msgs.append({"role": "user", "content": "一個鮪魚飯糰 白米"})
    msgs.append(
        {
            "role": "assistant",
            "content": None,
            "tool_calls": _tc(
                "c1",
                "add_item",
                {
                    "name": "鮪魚飯糰",
                    "rice": "白米",
                },
            ),
        }
    )
    msgs.append(
        _tool_resp(
            "c1", {"ok": True, "item_id": "riceball_1", "message": "已加入 1份 白米鮪魚飯糰", "cart_count": 1}
        )
    )
    msgs.append({"role": "assistant", "content": "好～還要什麼？"})

    # Demo 2: 載體直接 call — name 填完整品項名，後端自動拆出 carrier+flavor
    # 品項：培根蛋吐司（test cases 常用火腿蛋/起司蛋，此 demo 用培根蛋）
    msgs.append({"role": "user", "content": "一個培根蛋吐司"})
    msgs.append(
        {
            "role": "assistant",
            "content": None,
            "tool_calls": _tc(
                "c2",
                "add_item",
                {
                    "name": "培根蛋吐司",
                },
            ),
        }
    )
    msgs.append(
        _tool_resp(
            "c2",
            {"ok": True, "item_id": "carrier_1", "message": "已加入 1份 培根蛋吐司", "cart_count": 2},
        )
    )
    msgs.append({"role": "assistant", "content": "好～還要什麼？"})

    # Demo 3: 套餐帶溫度直接 call → ok:true（示範 add_item 最簡套餐呼叫）
    # 品項：套餐一 冰的（test cases 用套餐一缺溫度），示範「明確給溫度→直接 call」
    msgs.append({"role": "user", "content": "套餐一 冰的"})
    msgs.append(
        {
            "role": "assistant",
            "content": None,
            "tool_calls": _tc(
                "c3",
                "add_item",
                {
                    "name": "套餐一",
                    "temp": "冰",
                },
            ),
        }
    )
    msgs.append(
        _tool_resp(
            "c3",
            {
                "ok": True,
                "item_id": "combo_1",
                "message": "已加入 1份 套餐一",
                "cart_count": 3,
            },
        )
    )
    msgs.append({"role": "assistant", "content": "好～還要什麼？"})

    # Demo 4: 俗稱大冰奶→直接 call（size 必須用「大杯」）
    # 品項：大冰奶 = 大杯冰純鮮奶茶，示範俗稱→完整規格直接 call
    msgs.append({"role": "user", "content": "大冰奶"})
    msgs.append(
        {
            "role": "assistant",
            "content": None,
            "tool_calls": _tc(
                "c4x",
                "add_item",
                {
                    "name": "純鮮奶茶",
                    "size": "大杯",
                    "temp": "冰",
                },
            ),
        }
    )
    msgs.append(
        _tool_resp(
            "c4x",
            {
                "ok": True,
                "item_id": "drink_0",
                "message": "已加入 1份 大杯冰純鮮奶茶",
                "cart_count": 3,
            },
        )
    )
    msgs.append({"role": "assistant", "content": "好～還要什麼？"})

    # Demo 5: 多品項部分缺 — call 齊全的 + 追問缺的（含 add_item 飲料示範）
    # 品項：花生吐司（齊全）+ 大冰十穀漿（齊全）+ 奶茶（缺規格）
    # 教學：齊全先 call，缺的用簡稱追問（中冰/中溫）
    msgs.append({"role": "user", "content": "一個花生吐司 一杯大冰十穀漿 一杯奶茶"})
    msgs.append(
        {
            "role": "assistant",
            "content": None,
            "tool_calls": _tc(
                "c5a",
                "add_item",
                {
                    "name": "花生吐司",
                },
            ),
        }
    )
    msgs.append(
        _tool_resp(
            "c5a",
            {"ok": True, "item_id": "carrier_3", "message": "已加入 1份 花生吐司", "cart_count": 4},
        )
    )
    msgs.append(
        {
            "role": "assistant",
            "content": None,
            "tool_calls": _tc(
                "c5b",
                "add_item",
                {
                    "name": "十穀漿",
                    "size": "大杯",
                    "temp": "冰",
                },
            ),
        }
    )
    msgs.append(
        _tool_resp(
            "c5b",
            {"ok": True, "item_id": "drink_1", "message": "已加入 1份 大杯冰十穀漿", "cart_count": 5},
        )
    )
    msgs.append({"role": "assistant", "content": "好，奶茶要中冰還是中溫？"})

    # Demo 6: 結帳流程 → [CHECKOUT] tag（不用 tool call，系統攔截處理）
    msgs.append({"role": "user", "content": "好了 買單"})
    msgs.append({"role": "assistant", "content": f"{CHECKOUT_TAG}內用還是外帶？"})

    # Demo 7: 客人詢問菜單品項 → call query_menu(category="飲品") → 列舉回覆
    msgs.append({"role": "user", "content": "你們有什麼飲料"})
    msgs.append(
        {
            "role": "assistant",
            "content": None,
            "tool_calls": _tc(
                "c7",
                "query_menu",
                {"category": "飲品"},
            ),
        }
    )
    msgs.append(
        _tool_resp(
            "c7",
            {
                "ok": True,
                "category": "飲品",
                "items": ["有糖豆漿", "精選紅茶", "純鮮奶茶", "十穀漿", "黑糖純鮮奶茶"],
            },
        )
    )
    msgs.append(
        {
            "role": "assistant",
            "content": "我們有：有糖豆漿、精選紅茶、純鮮奶茶、十穀漿、黑糖純鮮奶茶，要點哪個？",
        }
    )

    # Demo 8: 套餐缺溫度 → call → ok:false → 追問（示範套餐必填溫度 + ok:false 反饋循環）
    # 品項：套餐三（test cases 用套餐一/四），覆蓋 combo_missing_temp
    msgs.append({"role": "user", "content": "一個三號餐"})
    msgs.append(
        {
            "role": "assistant",
            "content": None,
            "tool_calls": _tc(
                "c8",
                "add_item",
                {
                    "name": "套餐三",
                },
            ),
        }
    )
    msgs.append(_tool_resp("c8", {"ok": False, "message": "飲料冰的還是溫的"}))
    msgs.append({"role": "assistant", "content": "飲料要冰的還是溫的？"})

    # Demo 9: 取消品項用 [REMOVE] tag（不 call tool，系統攔截處理）
    # 購物車沒有奶茶的情境，覆蓋 cancel_nonexistent
    msgs.append({"role": "user", "content": "幫我把奶茶取消"})
    msgs.append(
        {"role": "assistant", "content": "[REMOVE:奶茶]購物車裡沒有奶茶喔，不用取消～還需要什麼？"}
    )

    return msgs
