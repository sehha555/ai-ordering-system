"""訂單路由器 - 物件介面"""
from typing import Dict, Any, List


# 同音字正規化
NORMALIZE_MAP = {"飯團": "飯糰"}


# 內嵌 keywords
RICE_KEYWORDS = ["白米", "紫米", "混米"]
RICEBALL_KEYWORDS = ["飯糰"]
FLAVOR_ALIASES = {"醬燒里肌": "醬燒里肌"}


SINGLE_ITEM_MARKERS = ["單點", "單獨"]
CARRIER_KEYWORDS = ["漢堡", "吐司", "饅頭"]
DRINK_KEYWORDS = ["豆漿", "紅茶", "綠茶", "鮮奶", "奶茶", "漿", "奶", "豆", "紅"]


EGG_PANCAKE_KEYWORDS = ["蛋餅"]


def normalize_text(text: str) -> str:
    t = text
    for wrong, correct in NORMALIZE_MAP.items():
        t = t.replace(wrong, correct)
    return t


def _route(text: str, current_order_has_main: bool = False) -> Dict[str, Any]:
    """內部路由邏輯"""
    t = normalize_text(text)

    # Exact SKU guard for "蛋餅飯糰"
    if "蛋餅飯糰" in t:
        return {"route_type": "riceball", "needs_clarify": False, "note": "exact_sku_guard:egg_pancake_riceball"}

    # 1. 單點
    if any(marker in t for marker in SINGLE_ITEM_MARKERS):
        return {"route_type": "snack", "needs_clarify": False, "note": "single_item_context"}

    # ---- 主要品項路由 (飯糰 > 蛋餅 > 載體 > 飲品) ----

    # 2. 飯糰 (關鍵字)
    if any(kw in t for kw in RICEBALL_KEYWORDS):
        return {"route_type": "riceball", "needs_clarify": False, "note": "hit:riceball_keywords"}

    # 3. 米種上下文
    if current_order_has_main and any(rice in t for rice in RICE_KEYWORDS):
        return {"route_type": "riceball", "needs_clarify": False, "note": "hit:rice_keyword_context"}
    
    # 4. 口味 (飯糰)
    for flavor, aliases in FLAVOR_ALIASES.items():
        if aliases in t:
            return {"route_type": "riceball", "needs_clarify": False, "note": f"hit:flavor({flavor})"}

    # 5. 米種兜底
    if any(rice in t for rice in RICE_KEYWORDS):
        return {"route_type": "riceball", "needs_clarify": False, "note": "hit:rice_keyword_fallback"}


    # 6. 蛋餅 (新增)
    if any(kw in t for kw in EGG_PANCAKE_KEYWORDS) and not any(kw in t for kw in RICEBALL_KEYWORDS):
        return {"route_type": "egg_pancake", "needs_clarify": False, "note": "hit:egg_pancake_keywords"}

    # 7. 載體 (漢堡/吐司/饅頭)
    if any(c in t for c in CARRIER_KEYWORDS):
        return {"route_type": "carrier", "needs_clarify": False, "note": "hit:carrier"}

    # 8. 飲料
    if any(kw in t for kw in DRINK_KEYWORDS):
        return {"route_type": "drink", "needs_clarify": False, "note": "hit:drink_keywords"}

    # ---- 結束主要品項路由 ----

    return {
        "route_type": "unknown",
        "needs_clarify": True,
        "clarify_question": "想點哪一類？飯糰、蛋餅、漢堡、饅頭、飲料或單點？",
        "frame": None,
        "note": None,
    }


# 物件介面（支援 order_router.route()）
class OrderRouter:
    def route(self, text: str, current_order_has_main: bool = False) -> Dict[str, Any]:
        return _route(text, current_order_has_main)


# 全域匯出
order_router = OrderRouter()


# ✅ Backward-compatible export for tests/legacy callers（方案 B）
def route(text: str, current_order_has_main: bool = False) -> Dict[str, Any]:
    return order_router.route(text, current_order_has_main)


if __name__ == "__main__":
    tests = ["我要一個飯糰", "我要一個飯團", "我要一個饅頭", "我要一杯豆漿", "黑糖奶茶", "黑糖饅頭", "我要單點薯餅"]
    for t in tests:
        result = order_router.route(t)
        print(t + " => " + result["route_type"])








