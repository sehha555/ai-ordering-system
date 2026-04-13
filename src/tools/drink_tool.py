"""飲料解析工具 - 完整簡寫 + 大冰規範 + size/temp 分離"""

from typing import Dict, List, Optional, Any

from src.config.config_loader import load_json_config
from src.tools.menu import menu_price_service
from src.tools.text_utils import parse_quantity as _parse_quantity_util

# 從 aliases_drink.json 載入別名常數
_cfg = load_json_config("aliases_drink.json")
DRINK_ALIASES = _cfg["drink_aliases"]
SIZE_MAP = _cfg["size_map"]
TEMP_MAP = _cfg["temp_map"]
SUGAR_MAP = _cfg["sugar_map"]
# temp_size_shortcuts 在 JSON 裡是 array，轉回 tuple
TEMP_SIZE_SHORTCUTS = {k: tuple(v) for k, v in _cfg["temp_size_shortcuts"].items()}


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
            "rawtext": text,
        }

        # 4. missing slots
        missing = []
        if not drink:
            missing.append("drink")
        if not temp:
            missing.append("temp")
        if not size:
            missing.append("size")

        frame["missing_slots"] = missing
        return frame

    def quote_drink_price(self, frame: Dict[str, Any]) -> Dict[str, Any]:
        drink_name = frame.get("drink")
        size = frame.get("size")
        quantity = frame.get("quantity", 1)

        if not drink_name:
            return {"ok": False, "message": "缺少飲料名稱，無法計價。"}
        if not size:
            return {"ok": False, "message": f"{drink_name}缺少杯型，無法計價。"}

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
                return {
                    "ok": False,
                    "message": f"找不到飲品品項：{drink_name}{size}，無法計價。",
                }
            except RuntimeError as e:
                raise e  # Let the DM catch menu loading errors
        except RuntimeError as e:
            raise e  # Let the DM catch menu loading errors

        total_price = base_price * quantity

        return {
            "ok": True,
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
            if k in text:
                return v
        return None

    def parse_temp(self, text: str) -> Optional[str]:
        for k, v in TEMP_MAP.items():
            if k in text:
                return v
        return None

    def parse_sugar(self, text: str) -> Optional[str]:
        for k, v in SUGAR_MAP.items():
            if k in text:
                return v
        return None

    def parse_quantity(self, text: str) -> int:
        return _parse_quantity_util(text, units=("杯",))

    def load_menu(self) -> List[Dict[str, Any]]:
        return menu_price_service.get_raw_menu()


# 全域實例
drink_tool = DrinkTool()
