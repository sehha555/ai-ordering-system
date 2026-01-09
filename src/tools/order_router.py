"""訂單路由器 - 物件介面"""
from typing import Dict, Any, List
from src.tools.snack_tool import snack_tool


# 同音字正規化
NORMALIZE_MAP = {"飯團": "飯糰"}


# 內嵌 keywords
RICE_KEYWORDS = ["白米", "紫米", "混米"]
RICEBALL_KEYWORDS = ["飯糰"]
FLAVOR_ALIASES = {"醬燒里肌": "醬燒里肌"}


SINGLE_ITEM_MARKERS = ["單點", "單獨"]
CARRIER_KEYWORDS = ["漢堡", "饅頭"] # "吐司" 關鍵字太寬泛，交給 jam_toast 優先處理
DRINK_KEYWORDS = ["豆漿", "紅茶", "綠茶", "鮮奶", "奶茶", "漿", "奶", "豆", "紅"]
SNACK_KEYWORDS = snack_tool.snack_keywords # 動態載入
JAM_TOAST_KEYWORDS = ["果醬吐司", "草莓", "花生", "蒜香", "奶酥", "巧克力"]


EGG_PANCAKE_KEYWORDS = ["蛋餅"]


def normalize_text(text: str) -> str:
    t = text
    for wrong, correct in NORMALIZE_MAP.items():
        t = t.replace(wrong, correct)
    return t


def _route(text: str, current_order_has_main: bool = False) -> Dict[str, Any]:
    t = normalize_text(text)

    # Exact SKU guard for "蛋餅飯糰"
    if "蛋餅飯糰" in t:
        return {"route_type": "riceball", "needs_clarify": False, "note": "exact_sku_guard:egg_pancake_riceball"}

    # 1. 單點 (直接歸類為點心)
    if any(marker in t for marker in SINGLE_ITEM_MARKERS):
        return {"route_type": "snack", "needs_clarify": False, "note": "single_item_context"}

    # ---- 主要品項路由 ----

    # 2. 飯糰
    if any(kw in t for kw in RICEBALL_KEYWORDS):
        return {"route_type": "riceball", "needs_clarify": False, "note": "hit:riceball_keywords"}
    if current_order_has_main and any(rice in t for rice in RICE_KEYWORDS):
        return {"route_type": "riceball", "needs_clarify": False, "note": "hit:rice_keyword_context"}
    for flavor, aliases in FLAVOR_ALIASES.items():
        if aliases in t:
            return {"route_type": "riceball", "needs_clarify": False, "note": f"hit:flavor({flavor})"}
    if any(rice in t for rice in RICE_KEYWORDS):
        return {"route_type": "riceball", "needs_clarify": False, "note": "hit:rice_keyword_fallback"}

    # 3. 蛋餅
    if any(kw in t for kw in EGG_PANCAKE_KEYWORDS) and not any(kw in t for kw in RICEBALL_KEYWORDS):
        return {"route_type": "egg_pancake", "needs_clarify": False, "note": "hit:egg_pancake_keywords"}

    # 4. 果醬吐司 (優先於一般載體)
    is_jam_toast = any(kw in t for kw in JAM_TOAST_KEYWORDS)
    is_toast_carrier = "吐司" in t or "薄片" in t or "厚片" in t
    if is_jam_toast and is_toast_carrier:
        return {"route_type": "jam_toast", "needs_clarify": False, "note": "hit:jam_toast_keywords"}

    # 5. 載體 (漢堡/吐司/饅頭)
    if any(c in t for c in CARRIER_KEYWORDS) or "吐司" in t: # 把吐司放回這裡作為 fallback
        return {"route_type": "carrier", "needs_clarify": False, "note": "hit:carrier"}

    # 6. 鮪魚蛋 (無載體時，應視為 carrier 問題)
    if "鮪魚" in t and "蛋" in t and not any(carrier_word in t for carrier_word in ["吐司","饅頭","漢堡","貝果","蛋餅","飯糰"]):
        return {"route_type": "carrier", "needs_clarify": False, "note": "hit:tuna_egg_needs_carrier"}

    # 7. 點心
    if any(kw in t for kw in SNACK_KEYWORDS):
        return {"route_type": "snack", "needs_clarify": False, "note": "hit:snack_keywords"}

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