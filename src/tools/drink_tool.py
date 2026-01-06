"""飲料解析工具 - 完整簡寫 + 大冰規範 + size/temp 分離"""
import re
from typing import Dict, List, Optional, Any

from src.tools.menu import menu_price_service
from src.tools.riceball_tool import _chinese_number_to_int # Import Chinese number parser

# 完整簡寫 + 大冰規範（長字優先）
DRINK_ALIASES = {
    # 大冰簡寫（最高優先）
    "大冰豆": "有糖豆漿", "大冰清": "無糖豆漿", "大冰紅": "精選紅茶",
    "大冰米": "花生糙米漿", "大冰混": "米漿+豆漿", "大冰薏": "燕麥薏仁漿",
    "大冰綠": "無糖清香綠茶", "大冰薏牛": "燕麥薏仁牛奶", 
    "大冰奶": "純鮮奶茶", "大冰黑糖": "黑糖純鮮奶茶", 
    "大冰咖": "純鮮奶咖啡", "大冰十穀": "十穀漿",
    
    # 單字簡寫
    "豆": "有糖豆漿", "清": "無糖豆漿", "紅": "精選紅茶", 
    "米": "花生糙米漿", "薏": "燕麥薏仁漿", "薏牛": "燕麥薏仁牛奶",
    "混": "米漿+豆漿", "綠": "無糖清香綠茶", "奶": "純鮮奶茶",
    "黑糖": "黑糖純鮮奶茶", "咖": "純鮮奶咖啡", "十穀": "十穀漿",
    
    # 完整別稱
    "有糖豆漿": "有糖豆漿", "豆漿": "有糖豆漿", "無糖豆漿": "無糖豆漿", "清漿": "無糖豆漿", 
    "白漿": "無糖豆漿", "花生糙米漿": "花生糙米漿", 
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

# 優先順序：先吃 shortcut，再退回單獨判斷
TEMP_SIZE_SHORTCUTS = {
    "大冰": ("大杯", "冰"), "中冰": ("中杯", "冰"), "小冰": ("中杯", "冰"),
    "大熱": ("大杯", "熱"), "中熱": ("中杯", "熱"), "小熱": ("中杯", "熱"),
    "大溫": ("大杯", "溫"), "中溫": ("中杯", "溫"), "小溫": ("中杯", "溫"),
}


class DrinkTool:
    def __init__(self):
        self.menu_items = self.load_menu()
    
    def parse_drink_utterance(self, text: str) -> Dict[str, Any]:
        """先拆 size/temp，再找 drink"""
        t = text.strip()
        
        # 1. 先解析 quantity/sugar
        qty = self.parse_quantity(t)
        sugar = self.parse_sugar(t)
        
        # 2. 解析 size/temp (優先使用 shortcut)
        size, temp = self.parse_size_temp_shortcut(t)
        if not size:
            size = self.parse_size(t)
        if not temp:
            temp = self.parse_temp(t)
        
        # 3. 再解析 drink
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
        
        # 4. missing slots
        missing = []
        if not drink: missing.append("drink")
        if not temp: missing.append("temp")
        if not size: missing.append("size")
        
        frame["missing_slots"] = missing
        return frame

    def quote_drink_price(self, frame: Dict[str, Any]) -> Dict[str, Any]:
        drink_name = frame.get("drink")
        size = frame.get("size")
        quantity = frame.get("quantity", 1)

        if not drink_name:
            return {"status": "error", "message": "缺少飲料名稱，無法計價。"}
        if not size:
            return {"status": "error", "message": f"{drink_name}缺少杯型，無法計價。"}

        base_price = None
        # Try "飲品名稱(杯型縮寫)" e.g. "有糖豆漿(中)"
        try:
            full_drink_name_short = f"{drink_name}({size[0]})"
            base_price = menu_price_service.get_price("飲品", full_drink_name_short)
        except KeyError:
            # Fallback to "飲品名稱(完整杯型)" e.g. "有糖豆漿(中杯)"
            try:
                full_drink_name_long = f"{drink_name}({size})"
                base_price = menu_price_service.get_price("飲品", full_drink_name_long)
            except KeyError:
                return {"status": "error", "message": f"找不到飲品品項：{drink_name}{size}，無法計價。"}
            except RuntimeError as e:
                raise e # Let the DM catch menu loading errors
        except RuntimeError as e:
            raise e # Let the DM catch menu loading errors

        total_price = base_price * quantity

        return {
            "status": "success",
            "drink": drink_name,
            "size": size,
            "quantity": quantity,
            "single_price": base_price,
            "total_price": total_price,
            "message": f"{quantity}杯{drink_name}{size}，共 {total_price}元",
        }
    
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
            return canonical
        
        return None

    def parse_size_temp_shortcut(self, text: str) -> (Optional[str], Optional[str]):
        """解析尺寸溫度快捷鍵"""
        for shortcut, (size, temp) in TEMP_SIZE_SHORTCUTS.items():
            if shortcut in text:
                return size, temp
        return None, None
    
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
        m = re.search(r'(\d+)\s*杯?', text) # Matches digits and optional "杯"
        if m: return int(m.group(1)) if int(m.group(1)) > 0 else 1

        m_cn = re.search(r'([一二兩三四五六七八九十]{1,3})\s*杯?', text) # Matches Chinese numbers and optional "杯"
        if m_cn:
            val = _chinese_number_to_int(m_cn.group(1))
            if val is not None and val > 0:
                return val

        return 1
    
    def load_menu(self) -> List[Dict[str, Any]]:
        return menu_price_service.get_raw_menu()

# 全域實例
drink_tool = DrinkTool()
