"""
Few-shot priming messages — 讓本地 LLM 學會使用 text tag 格式輸出行動。

根因：LM Studio + Qwen3/2.5 需要示範對話才能正確判斷
何時輸出 [ADD:...] tag、何時直接追問、何時用 [QUERY:...] tag。

架構改變（text tag vs tool_calls）：
- 不再使用 tool_calls 欄位與 role:tool response
- 模型直接在 content 中輸出 tag（[ADD:...]、[QUERY:...]）
- backend 解析 tag 後自行執行，模型不需要看執行結果
- ok:false 場景改為「缺必填資訊就不加 tag，直接追問」

注意：超過 9 demo 可能觸發 few-shot collapse（riceball/carrier/combo 退化）
"""

# LLM 回覆中的結帳標記（voice_router 攔截用）
CHECKOUT_TAG = "[CHECKOUT]"


def get_priming_messages() -> list[dict]:
    """精選 priming 示範，教模型用 text tag 格式輸出點餐行動。

    9 個高質量 demo，品項全部與 test_scenarios.json 不重疊（防記憶化）：
    1. 飯糰完整 → [ADD:鮪魚飯糰|rice=白米]
    2. 載體直接 → [ADD:培根蛋吐司]
    3. 套餐帶溫度 → [ADD:套餐一|temp=冰]
    4. 俗稱大冰奶 → [ADD:純鮮奶茶|size=大杯|temp=冰]
    5. 多品項部分缺 → 齊全的先加 tag，缺的追問
    6. 結帳 → [CHECKOUT] tag
    7. 查飲品菜單 → [QUERY:飲品] + 列舉回覆
    8. 套餐缺溫度 → 不加 tag，直接追問（關鍵：缺必填時不輸出 [ADD:...]）
    9. 取消品項 → [REMOVE:奶茶] tag
    10. 更換品項 → [REMOVE:舊] + [ADD:新] 同時用
    """
    msgs: list[dict] = []

    # Demo 1: 飯糰完整 — 直接輸出 [ADD:...] tag，不需要等工具確認
    # 品項：鮪魚飯糰白米（示範 rice 必填參數格式）
    msgs.append({"role": "user", "content": "一個鮪魚飯糰 白米"})
    msgs.append({"role": "assistant", "content": "[ADD:鮪魚飯糰|rice=白米]好～還要什麼？"})

    # Demo 2: 載體直接 — 完整品項名，不帶額外參數
    # 品項：培根蛋吐司（test cases 常用火腿蛋/起司蛋，此 demo 用培根蛋）
    msgs.append({"role": "user", "content": "一個培根蛋吐司"})
    msgs.append({"role": "assistant", "content": "[ADD:培根蛋吐司]好～還要什麼？"})

    # Demo 3: 套餐帶溫度 — 示範「明確給溫度 → 直接加 tag」
    # 品項：套餐一冰的（test cases 用套餐一缺溫度，此 demo 示範完整版）
    msgs.append({"role": "user", "content": "套餐一 冰的"})
    msgs.append({"role": "assistant", "content": "[ADD:套餐一|temp=冰]好～還要什麼？"})

    # Demo 4: 俗稱大冰奶 → 正規化為完整規格再輸出 tag
    # 大冰奶 = 大杯冰純鮮奶茶，size 必須用「大杯」
    msgs.append({"role": "user", "content": "大冰奶"})
    msgs.append({"role": "assistant", "content": "[ADD:純鮮奶茶|size=大杯|temp=冰]好～還要什麼？"})

    # Demo 5: 多品項部分缺 — 齊全的先加 tag，缺規格的奶茶直接追問
    # 品項：花生吐司（齊全）+ 大冰十穀漿（齊全）+ 奶茶（缺 size/temp）
    msgs.append({"role": "user", "content": "一個花生吐司 一杯大冰十穀漿 一杯奶茶"})
    msgs.append(
        {
            "role": "assistant",
            "content": "[ADD:花生吐司][ADD:十穀漿|size=大杯|temp=冰]好，奶茶要中冰還是中溫？",
        }
    )

    # Demo 6: 結帳流程 → [CHECKOUT] tag（系統攔截處理，不需要額外 tag）
    msgs.append({"role": "user", "content": "好了 買單"})
    msgs.append({"role": "assistant", "content": f"{CHECKOUT_TAG}內用還是外帶？"})

    # Demo 7: 查菜單 → [QUERY:飲品] tag，再列舉回覆
    # 重要：[QUERY:...] tag 由 backend 解析，模型自行列舉結果
    msgs.append({"role": "user", "content": "菜單上有什麼可以喝的"})
    msgs.append(
        {
            "role": "assistant",
            "content": "[QUERY:飲品]我們有：有糖豆漿、精選紅茶、純鮮奶茶、十穀漿、黑糖純鮮奶茶，要點哪個？",
        }
    )

    # Demo 8: 套餐缺溫度 → 不加 [ADD:...] tag，直接追問（關鍵示範）
    # 教學：缺必填欄位時禁止輸出 [ADD:...] tag，先確認再說
    # 品項：套餐三（test cases 用套餐一/四），覆蓋 combo_missing_temp
    msgs.append({"role": "user", "content": "一個三號餐"})
    msgs.append({"role": "assistant", "content": "飲料要冰的還是溫的？"})

    # Demo 9: 取消品項用 [REMOVE] tag（系統攔截處理）
    # 購物車沒有奶茶的情境，覆蓋 cancel_nonexistent
    msgs.append({"role": "user", "content": "幫我把奶茶取消"})
    msgs.append(
        {"role": "assistant", "content": "[REMOVE:奶茶]購物車裡沒有奶茶喔，不用取消～還需要什麼？"}
    )

    # Demo 10: 更換品項 → [REMOVE] + [ADD] 同時使用
    msgs.append({"role": "user", "content": "甜飯糰換源味飯糰"})
    msgs.append(
        {
            "role": "assistant",
            "content": "[REMOVE:甜飯糰][ADD:源味傳統飯糰|rice=白米]好，已換成白米源味傳統飯糰～還要什麼？",
        }
    )

    return msgs
