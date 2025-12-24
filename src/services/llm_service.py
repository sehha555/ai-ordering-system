"""
LLM Service - 串接 LM Studio + menu_tool 的端到端點餐
"""

from typing import Dict, Any, List
import json
import requests
from src.tools.menu_tool import menu_tool

LM_STUDIO_URL = "http://localhost:1234/v1/chat/completions"
MODEL_NAME = "你的模型名稱"  # 例如: "qwen2.5:7b-instruct-q5_K_M"


def process_riceball_order(text: str) -> Dict[str, Any]:
    """
    端到端：從客人口語 → 訂單 JSON + 總價
    """
    # Step 1: parse_riceball_utterance
    frame = menu_tool.parse_riceball_utterance(text)
    
    if not frame.get("flavor"):
        return {
            "status": "incomplete",
            "order": frame,
            "message": "請確認口味",
            "needs_clarify": ["flavor"]
        }
    
    # Step 2: 檢查特殊客製
    if frame.get("needs_price_confirm"):
        addon_quote = menu_tool.quote_riceball_customization_price(
            flavor=frame["flavor"],
            add_ingredients=frame.get("ingredients_add", []),
            only_ingredients=frame.get("ingredients_only", []),
            only_mode=(frame["ingredients_mode"] == "only")
        )
        return {
            "status": "needs_price_confirm",
            "order": frame,
            "addon_quote": addon_quote,
            "message": f"特殊客製，請選價格：{addon_quote['suggested_prices'][:5]}..."  # 只顯示前5個
        }
    
    # Step 3: 正常報價
    base_quote = menu_tool.quote_riceball_price(
        flavor=frame["flavor"],
        large=frame["large"],
        heavy=frame["heavy"],
        extra_egg=frame["extra_egg"]
    )
    
    addon_quote = menu_tool.quote_riceball_customization_price(
        flavor=frame["flavor"],
        add_ingredients=frame.get("ingredients_add", []),
        remove_ingredients=frame.get("ingredients_remove", [])
    )
    
    # Step 4: 合併訂單
    total_price = base_quote["total_price"] + (addon_quote["addon_total"] or 0)
    
    order = {
        "item_type": "riceball",
        "quantity": frame["quantity"],
        "spec": {
            "flavor": frame["flavor"],
            "rice": frame["rice"],
            "large": frame["large"],
            "heavy": frame["heavy"],
            "extra_egg": frame["extra_egg"],
            "ingredients_add": frame["ingredients_add"],
            "ingredients_remove": frame["ingredients_remove"],
            "ingredients_mode": frame["ingredients_mode"],
        },
        "base_price": base_quote["total_price"],
        "addon_price": addon_quote["addon_total"],
        "total_price": total_price * frame["quantity"],
        "raw_text": frame["raw_text"]
    }
    
    return {
        "status": "complete",
        "order": order,
        "base_quote": base_quote,
        "addon_quote": addon_quote,
        "message": f"訂單完成，總價 {order['total_price']} 元"
    }


def test_end_to_end():
    """測試端到端流程"""
    tests = [
        "源味傳統加起司紫米",
        "醬燒里肌重量加蛋白米", 
        "源味傳統只要肉鬆",
        "只要飯跟蛋"
    ]
    
    for text in tests:
        print(f"\n=== 測試：'{text}' ===")
        result = process_riceball_order(text)
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    test_end_to_end()




