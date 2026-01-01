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
DRINK_KEYWORDS = [
    "豆漿", "無糖豆漿", "清漿", "白漿", "米漿", "糙米漿", "薏仁漿", 
    "十穀漿", "五穀漿", "豆紅", "紅豆", "鮮奶茶", "奶茶", "紅茶", 
    "綠茶", "混漿", "薏牛", "咖啡", "黑糖奶茶", "黑糖"
]

def normalize_text(text: str) -> str:
    t = text
    for wrong, correct in NORMALIZE_MAP.items():
        t = t.replace(wrong, correct)
    return t

def _route(text: str, current_order_has_main: bool = False) -> Dict[str, Any]:
    """內部路由邏輯"""
    t = normalize_text(text)
    
    # 1. 單點
    if any(marker in t for marker in SINGLE_ITEM_MARKERS):
        return {'route_type': 'snack', 'needs_clarify': False, 'note': 'single_item_context'}
    
    # 2. carrier
    if any(c in t for c in CARRIER_KEYWORDS):
        return {'route_type': 'carrier', 'needs_clarify': False, 'note': 'hit:carrier'}
    
    # 3. 飲料
    if any(kw in t for kw in DRINK_KEYWORDS):
        return {'route_type': 'drink', 'needs_clarify': False, 'note': 'hit:drink_keywords'}
    
    # 4. 米種上下文
    if current_order_has_main and any(rice in t for rice in RICE_KEYWORDS):
        return {'route_type': 'riceball', 'needs_clarify': False, 'note': 'hit:rice_keyword_context'}
    
    # 5. 飯糰
    if any(kw in t for kw in RICEBALL_KEYWORDS):
        return {'route_type': 'riceball', 'needs_clarify': False, 'note': 'hit:riceball_keywords'}
    
    # 6. 口味
    for flavor, aliases in FLAVOR_ALIASES.items():
        if aliases in t:
            return {'route_type': 'riceball', 'needs_clarify': False, 'note': f'hit:flavor({flavor})'}
    
    # 7. 米種兜底
    if any(rice in t for rice in RICE_KEYWORDS):
        return {'route_type': 'riceball', 'needs_clarify': False, 'note': 'hit:rice_keyword_fallback'}
    
    return {
        'route_type': 'unknown',
        'needs_clarify': True,
        'clarify_question': '想點哪一類？飯糰、漢堡、饅頭、飲料或單點？',
        'frame': None,
        'note': None
    }

# ✅ 物件介面（支援 order_router.route()）
class OrderRouter:
    def route(self, text: str, current_order_has_main: bool = False) -> Dict[str, Any]:
        return _route(text, current_order_has_main)

# ✅ 全域匯出
order_router = OrderRouter()

if __name__ == "__main__":
    tests = ['我要一個飯糰','我要一個飯團','我要一個饅頭','我要一杯豆漿','黑糖奶茶','黑糖饅頭','我要單點薯餅']
    for t in tests:
        result = order_router.route(t)
        print(t + ' => ' + result['route_type'])







