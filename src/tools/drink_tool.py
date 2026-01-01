"""飲料解析工具 - 完整簡寫 + 大冰規範 + size/temp 分離"""
import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Any

MENU_FILE = Path(__file__).parent / "menu" / "menu_all.json"

# 完整簡寫 + 大冰規範（長字優先）
DRINK_ALIASES = {
    # 大冰簡寫（最高優先）
    "大冰豆": "豆漿", "大冰清": ("豆漿", "無糖"), "大冰紅": "精選紅茶",
    "大冰米": "花生糙米漿", "大冰混": "米漿+豆漿", "大冰薏": "燕麥薏仁漿",
    "大冰綠": "無糖清香綠茶", "大冰薏牛": "燕麥薏仁牛奶", 
    "大冰奶": "純鮮奶茶", "大冰黑糖": "黑糖純鮮奶茶", 
    "大冰咖": "純鮮奶咖啡", "大冰十穀": "五穀漿",
    
    # 單字簡寫
    "豆": "豆漿", "清": ("豆漿", "無糖"), "紅": "精選紅茶", 
    "米": "花生糙米漿", "薏": "燕麥薏仁漿", "薏牛": "燕麥薏仁牛奶",
    "混": "米漿+豆漿", "綠": "無糖清香綠茶", "奶": "純鮮奶茶",
    "黑糖": "黑糖純鮮奶茶", "咖": "純鮮奶咖啡", "十穀": "五穀漿",
    
    # 完整別稱
    "豆漿": "豆漿", "無糖豆漿": ("豆漿", "無糖"), "清漿": ("豆漿", "無糖"), 
    "白漿": ("豆漿", "無糖"), "花生糙米漿": "花生糙米漿", 
    "糙米漿": "花生糙米漿", "燕麥薏仁漿": "燕麥薏仁漿", 
    "五穀漿": "五穀漿", "豆紅": "紅豆", "紅豆": "紅豆",
    "純鮮奶茶": "純鮮奶茶", "鮮奶茶": "純鮮奶茶", "奶茶": "純鮮奶茶",
    "精選紅茶": "精選紅茶", "無糖清香綠茶": "無糖清香綠茶",
    "米漿+豆漿": "米漿+豆漿", "燕麥薏仁牛奶": "燕麥薏仁牛奶",
    "純鮮奶咖啡": "純鮮奶咖啡"
}

SIZE_MAP = {"大": "大杯", "中": "中杯", "小": "中杯"}
TEMP_MAP = {"冰": "冰", "溫": "溫", "熱": "熱", "冷的": "冰", "熱的": "熱"}
SUGAR_MAP = {"無糖": "無糖", "半糖": "半糖", "有糖": "有糖"}

class DrinkTool:
    def __init__(self):
        self.menu_items = self.load_menu()
    
    def parse_drink_utterance(self, text: str) -> Dict[str, Any]:
        """先拆 size/temp，再找 drink"""
        t = text.strip()
        
        # 1. 先解析 size/temp/quantity/sugar
        qty = self.parse_quantity(t)
        size = self.parse_size(t)
        temp = self.parse_temp(t)
        sugar = self.parse_sugar(t)
        
        # 2. 再解析 drink
        drink = self.detect_drink(t)
        
        frame = {
            "itemtype": "drink",
            "drink": drink,
            "quantity": qty,
            "size": size,
            "temp": temp,
            "sugar": sugar,
            "rawtext": text
        }
        
        # 3. missing slots
        missing = []
        if not drink: missing.append("drink")
        if not temp: missing.append("temp")
        if not size: missing.append("size")
        
        frame["missing_slots"] = missing
        return frame
    
    def detect_drink(self, text: str) -> Optional[str]:
        """長字優先全匹配"""
        t = text
        candidates = []
        for alias, canonical in DRINK_ALIASES.items():
            if alias in t:
                candidates.append((len(alias), alias, canonical))
        
        # 按長度降序排序（長字優先）
        candidates.sort(key=lambda x: x[0], reverse=True)
        
        if candidates:
            _, matched_alias, canonical = candidates[0]
            return canonical if isinstance(canonical, str) else canonical[0]
        
        return None
    
    def parse_size(self, text: str) -> Optional[str]:
        for k, v in SIZE_MAP.items():
            if k in text: return v
        return None
    
    def parse_temp(self, text: str) -> Optional[str]:
        for k, v in TEMP_MAP.items():
            if k in text: return v
        return None
    
    def parse_sugar(self, text: str) -> Optional[str]:
        for k, v in SUGAR_MAP.items():
            if k in text: return v
        return None
    
    def parse_quantity(self, text: str) -> int:
        m = re.search(r'(\d+)', text)
        if m: return int(m.group(1)) if int(m.group(1)) > 0 else 1
        return 1
    
    def load_menu(self) -> List[Dict[str, Any]]:
        try:
            with open(MENU_FILE, 'r', encoding='utf-8-sig') as f:
                data = json.load(f)
                return data if isinstance(data, list) else data.get('items', [])
        except FileNotFoundError:
            return []

# 全域實例
drink_tool = DrinkTool()




