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

    11 個高質量 demo，品項全部與 test_scenarios.json 不重疊（防記憶化）：
    1. 飯糰完整 call — boolean spicy + flavor 不帶後綴（修 Pattern C 參數格式）
    2. 載體缺 → 追問 → 補齊後 call（培根蛋，避開 test 火腿蛋/起司蛋）
    3. 套餐帶溫度直接 call → ok:true（套餐五，防套餐一記憶化）
    4. 俗稱大溫奶→直接 call（大杯溫純鮮奶茶，size=「大杯」；用溫版防大冰奶記憶化）
    5. 多品項部分缺 — add_carrier + add_drink 齊全先 call，奶茶缺規格追問
    6. 結帳完整流程 → [CHECKOUT] tag
    7. 菜單查詢 → call query_menu(category="小吃") → 列舉（用小吃防飲品記憶化）
    8. 套餐數字別名 → call → ok:false → 追問（combo_missing_temp / combo_alias）
    9. 取消不存在品項 → [REMOVE] tag（cancel_nonexistent）
    10. 空購物車結帳 → 提示購物車是空的（checkout_empty_cart）
    11. 空購物車修改 → 提示沒有品項（modify_empty_cart）
    """
    msgs: list[dict] = []

    # Demo 1: 飯糰完整 call — 示範 boolean spicy=false + flavor 只填口味名稱
    # 品項：鮭魚（test cases 沒有此品項），修正 Pattern C（riceball 參數格式錯誤）
    msgs.append({"role": "user", "content": "一個鮭魚飯糰 白米 不加辣"})
    msgs.append(
        {
            "role": "assistant",
            "content": None,
            "tool_calls": _tc(
                "c1",
                "add_riceball",
                {
                    "flavor": "鮭魚",
                    "rice": "白米",
                    "spicy": False,
                },
            ),
        }
    )
    msgs.append(
        _tool_resp(
            "c1", {"ok": True, "item_id": "rb_1", "message": "已加入 1份 白米鮭魚", "cart_count": 1}
        )
    )
    msgs.append({"role": "assistant", "content": "好～還要什麼？"})

    # Demo 2: 載體缺 → 追問 → 補齊後 call（完整多輪循環）
    # 品項：培根蛋（test cases 用起司蛋/火腿蛋），覆蓋「缺必填→追問→補齊→call」
    msgs.append({"role": "user", "content": "一個培根蛋"})
    msgs.append({"role": "assistant", "content": "吐司還是漢堡？"})
    msgs.append({"role": "user", "content": "吐司"})
    msgs.append(
        {
            "role": "assistant",
            "content": None,
            "tool_calls": _tc(
                "c2",
                "add_carrier",
                {
                    "carrier": "吐司",
                    "flavor": "培根蛋",
                },
            ),
        }
    )
    msgs.append(
        _tool_resp(
            "c2",
            {"ok": True, "item_id": "cr_1", "message": "已加入 1份 培根蛋吐司", "cart_count": 2},
        )
    )
    msgs.append({"role": "assistant", "content": "好～還要什麼？"})

    # Demo 3: 套餐帶溫度直接 call → ok:true（示範 add_combo 最簡呼叫）
    # 品項：套餐五（test cases 不含此品項，防止套餐一/四 被記憶化）
    msgs.append({"role": "user", "content": "套餐五 冰的"})
    msgs.append(
        {
            "role": "assistant",
            "content": None,
            "tool_calls": _tc(
                "c3",
                "add_combo",
                {
                    "combo_name": "套餐五",
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
                "item_id": "cb_1",
                "message": "已加入 1份 套餐五",
                "cart_count": 3,
            },
        )
    )
    msgs.append({"role": "assistant", "content": "好～還要什麼？"})

    # Demo 4: 俗稱大溫奶→直接 call（示範 size=大杯 不追問，防 intent_big_iced_milk 記憶化）
    # 品項：大溫奶 = 大杯溫純鮮奶茶（test case 用大冰奶，刻意用溫版避免 exact match）
    msgs.append({"role": "user", "content": "大溫奶"})
    msgs.append(
        {
            "role": "assistant",
            "content": None,
            "tool_calls": _tc(
                "c4x",
                "add_drink",
                {
                    "flavor": "純鮮奶茶",
                    "size": "大杯",
                    "temp": "溫",
                },
            ),
        }
    )
    msgs.append(
        _tool_resp(
            "c4x",
            {
                "ok": True,
                "item_id": "dk_0",
                "message": "已加入 1份 大杯溫純鮮奶茶",
                "cart_count": 3,
            },
        )
    )
    msgs.append({"role": "assistant", "content": "好～還要什麼？"})

    # Demo 5: 多品項部分缺 — call 齊全的 + 追問缺的（含 add_drink 示範）
    # 品項：花生吐司 + 大冰十穀漿（齊全） + 奶茶（缺規格）
    # 教學：齊全先 call（含 add_drink），缺的用簡稱追問（中冰/中溫）
    msgs.append({"role": "user", "content": "一個花生吐司 一杯大冰十穀漿 一杯奶茶"})
    msgs.append(
        {
            "role": "assistant",
            "content": None,
            "tool_calls": _tc(
                "c5a",
                "add_carrier",
                {
                    "carrier": "吐司",
                    "flavor": "花生",
                },
            ),
        }
    )
    msgs.append(
        _tool_resp(
            "c5a",
            {"ok": True, "item_id": "cr_3", "message": "已加入 1份 花生吐司", "cart_count": 4},
        )
    )
    msgs.append(
        {
            "role": "assistant",
            "content": None,
            "tool_calls": _tc(
                "c5b",
                "add_drink",
                {
                    "flavor": "十穀漿",
                    "size": "大杯",
                    "temp": "冰",
                },
            ),
        }
    )
    msgs.append(
        _tool_resp(
            "c5b",
            {"ok": True, "item_id": "dk_1", "message": "已加入 1份 大杯冰十穀漿", "cart_count": 5},
        )
    )
    msgs.append({"role": "assistant", "content": "好，奶茶要中冰還是中溫？"})

    # Demo 6: 結帳流程 → [CHECKOUT] tag（不用 tool call，系統攔截處理）
    msgs.append({"role": "user", "content": "好了 買單"})
    msgs.append({"role": "assistant", "content": f"{CHECKOUT_TAG}內用還是外帶？"})

    # Demo 7: 客人詢問菜單品項 → call query_menu 取得分類清單後列舉
    # 情境：問小吃有什麼（test case 問飲料，刻意用不同分類防記憶化），示範 query_menu 呼叫
    msgs.append({"role": "user", "content": "你們有什麼小吃"})
    msgs.append(
        {
            "role": "assistant",
            "content": None,
            "tool_calls": _tc(
                "c7",
                "query_menu",
                {"category": "小吃"},
            ),
        }
    )
    msgs.append(
        _tool_resp(
            "c7",
            {
                "ok": True,
                "category": "小吃",
                "items": ["薯餅", "蘿蔔糕", "哈希布朗"],
            },
        )
    )
    msgs.append(
        {
            "role": "assistant",
            "content": "我們有：薯餅、蘿蔔糕、哈希布朗，要哪個？",
        }
    )

    # Demo 8: 套餐數字別名 → call → ok:false → 追問（示範別名解析 + ok:false 反饋循環）
    # 品項：三號餐（test cases 用套餐一/四），覆蓋 combo_missing_temp / combo_alias
    msgs.append({"role": "user", "content": "一個三號餐"})
    msgs.append(
        {
            "role": "assistant",
            "content": None,
            "tool_calls": _tc(
                "c8",
                "add_combo",
                {
                    "combo_name": "套餐三",
                },
            ),
        }
    )
    msgs.append(_tool_resp("c8", {"ok": False, "message": "缺飲料溫度，冰的還是溫的？"}))
    msgs.append({"role": "assistant", "content": "飲料要冰的還是溫的？"})

    # Demo 9: 取消品項用 [REMOVE] tag（不 call tool，系統攔截處理）
    # 購物車沒有奶茶的情境，覆蓋 cancel_nonexistent
    msgs.append({"role": "user", "content": "幫我把奶茶取消"})
    msgs.append(
        {"role": "assistant", "content": "[REMOVE:奶茶]購物車裡沒有奶茶喔，不用取消～還需要什麼？"}
    )

    # Demo 10: 空購物車結帳 → 提示購物車是空的（不 call tool，不走 [CHECKOUT]）
    # 情境：看到 session_context 購物車：空 + 結帳 → 先提示空車
    msgs.append({"role": "system", "content": "# 當前狀態\n購物車：空"})
    msgs.append({"role": "user", "content": "結帳"})
    msgs.append({"role": "assistant", "content": "購物車是空的喔，要先點餐才能結帳！"})

    # Demo 11: 空購物車修改 → 提示沒有該品項（不 call tool）
    # 情境：看到 session_context 購物車：空 + 修改請求 → 提示沒有
    msgs.append({"role": "system", "content": "# 當前狀態\n購物車：空"})
    msgs.append({"role": "user", "content": "把豆漿換成奶茶"})
    msgs.append({"role": "assistant", "content": "購物車裡沒有豆漿喔，要先點餐再換！"})

    return msgs
