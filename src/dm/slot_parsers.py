import re
from typing import Dict, Any


def parse_strict_price_confirm(text: str, *, min_price: int = 35, step: int = 5) -> Dict[str, Any]:
    t = (text or "").strip()

    m = re.search(r"(\d{2,3})", t)
    if not m:
        return {
            "ok": False,
            "price": None,
            "reason": "missing_number",
            "message": f"你想要包多少錢的？請直接說價格（最低{min_price}元、{step}元級距，例如{min_price}/{min_price+step}/{min_price+2*step}）。",
        }

    v = int(m.group(1))

    if v < min_price:
        return {
            "ok": False,
            "price": None,
            "reason": "below_min",
            "message": f"最低是 {min_price} 元喔。你想包 {min_price}/{min_price+step}/{min_price+2*step} 哪個？",
        }

    if v % step != 0:
        return {
            "ok": False,
            "price": None,
            "reason": "not_multiple_of_step",
            "message": f"價格請用 {step} 元級距喔（例如 {min_price}/{min_price+step}/{min_price+2*step}）。你想包多少？",
        }

    return {"ok": True, "price": v, "reason": None, "message": None}


def parse_rice_choice(text: str) -> Dict[str, Any]:
    """
    只在「系統正在追問米種」的 pending 狀態使用：
    - 紫米同義詞：紫的 / 黑的 / 黑米 / 紫糯米 / 黑糯米
    - 白米同義詞：白的 / 白米 / 白糯米 / 正常
    - 混米同義詞：紫米白米混合 / 混米 / 一半一半
    """
    t = (text or "").strip()

    # 先判斷混米（避免被紫/白關鍵字先吃掉）
    mix = ["紫米白米混合", "紫米白米", "紫白混合", "混米", "混合", "一半一半"]
    purple = ["紫糯米", "黑糯米", "黑米", "紫米", "紫的", "黑的"]
    white = ["白糯米", "白米", "白的", "正常"]

    for kw in mix:
        if kw in t:
            return {"ok": True, "rice": "混米", "message": None}

    for kw in purple:
        if kw in t:
            return {"ok": True, "rice": "紫米", "message": None}

    for kw in white:
        if kw in t:
            return {"ok": True, "rice": "白米", "message": None}

    return {"ok": False, "rice": None, "message": "請問要白米、紫米還是混米？"}

