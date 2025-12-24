"""
LLM Service - 確定性飯糰點餐（後端模板 + LLM 解析）
"""

import json
import requests
from typing import Dict, Any, List
from src.tools.menu_tool import menu_tool

LM_STUDIO_URL = "http://127.0.0.1:1234/v1/chat/completions"
MODEL_NAME = "qwen2.5-14b-instruct-1m"

def execute_tool_call(tool_call: Dict[str, Any]) -> Dict[str, Any]:
    func_name = tool_call["function"]["name"]
    args = json.loads(tool_call["function"]["arguments"])
    
    if func_name == "parse_riceball_utterance":
        return menu_tool.parse_riceball_utterance(**args)
    elif func_name == "quote_riceball_price":
        return menu_tool.quote_riceball_price(**args)
    elif func_name == "quote_riceball_customization_price":
        return menu_tool.quote_riceball_customization_price(**args)
    return {"error": f"未知工具: {func_name}"}

def process_riceball_conversation(user_input: str) -> str:
    messages = [{"role": "user", "content": user_input}]
    
    response1 = requests.post(
        LM_STUDIO_URL,
        json={
            "model": MODEL_NAME,
            "messages": messages,
            "tools": menu_tool.get_openai_tools_schema(),
            "tool_choice": "required",
            "temperature": 0.0,
        },
        timeout=60
    ).json()
    
    tool_calls = response1["choices"][0]["message"].get("tool_calls", [])
    if not tool_calls:
        return "請再說清楚一點！"
    
    frame = execute_tool_call(tool_calls[0])
    flavor = frame.get("flavor", "未知口味")
    rice = frame.get("rice", "未知米種")
    needs_price_confirm = frame.get("needs_price_confirm", False)
    
    if needs_price_confirm:
        return f"{flavor}只要{frame.get('ingredients_only', ['配料'])}，請問你要包 35 還是 40？"
    elif not frame.get("rice"):
        return f"{flavor}請問要白米、紫米還是混米？"
    else:
        base_quote = menu_tool.quote_riceball_price(
            flavor=flavor,
            large=frame.get("large", False),
            heavy=frame.get("heavy", False),
            extra_egg=frame.get("extra_egg", False)
        )
        addon_quote = menu_tool.quote_riceball_customization_price(
            flavor=flavor,
            add_ingredients=frame.get("ingredients_add", [])
        )
        total = base_quote["total_price"] + (addon_quote["addon_total"] or 0)
        
        spec = []
        if frame.get("large"): spec.append("加大")
        if frame.get("heavy"): spec.append("重量版")
        if frame.get("extra_egg"): spec.append("加蛋")
        if frame.get("ingredients_add"): spec.append("+" + ",".join(frame["ingredients_add"]))
        
        return f"{flavor}{rice}{'·'.join(spec) if spec else ''}，共 {total} 元，對嗎？"

if __name__ == "__main__":
    print("確定性飯糰點餐測試")
    tests = [
        "源味傳統加起司紫米",
        "源味傳統只要肉鬆", 
        "醬燒里肌重量加蛋白米",
        "我要一個源味"
    ]
    for text in tests:
        print(f"\n客人：{text}")
        print("=" * 50)
        reply = process_riceball_conversation(text)
        print(f"助手：{reply}")
        print("-" * 50)








