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

# 預排序別名（長字優先匹配）
_ALIASES_SORTED = tuple(sorted(DRINK_ALIASES.keys(), key=len, reverse=True))

_MODIFIER_PREFIXES = tuple(
    sorted(
        set(TEMP_SIZE_SHORTCUTS) | set(SIZE_MAP) | set(TEMP_MAP) | set(SUGAR_MAP),
        key=len,
        reverse=True,
    )
)


def resolve_flavor(value: Optional[str]) -> Optional[str]:
    """飲料別名 → 標準名。value 已是菜單標準名（含混合品項「紅茶+豆漿」）
    直接回傳 — 別名表子字串匹配會把混合品名吃成組成單品（「豆漿」in
    「紅茶+豆漿」→ 有糖豆漿，b12-05）"""
    if value is None:
        return None
    try:
        menu_price_service.get_price("飲品", f"{value}(中)")
        return value
    except KeyError:
        pass
    for alias in _ALIASES_SORTED:
        if alias == value or alias in value:
            return DRINK_ALIASES[alias]
    return value


def resolve_size(value: Optional[str]) -> Optional[str]:
    """杯型別名 → 標準名"""
    if value is None:
        return None
    for k, v in SIZE_MAP.items():
        if k == value or k in value:
            return v
    return value


def resolve_temp(value: Optional[str]) -> Optional[str]:
    """溫度別名 → 標準名"""
    if value is None:
        return None
    for k, v in TEMP_MAP.items():
        if k == value or k in value:
            return v
    return value


def is_valid_drink_input(name: str) -> bool:
    """驗證 name 是合法飲料輸入，避免子字串誤匹配（如「珍珠奶茶」透過「奶茶」）"""
    if name in DRINK_ALIASES:
        return True
    for prefix in _MODIFIER_PREFIXES:
        if name.startswith(prefix):
            remainder = name[len(prefix) :]
            if remainder and remainder in DRINK_ALIASES:
                return True
    return False


def build_cart_item(
    flavor: Optional[str] = None,
    size: Optional[str] = None,
    temp: Optional[str] = None,
    quantity: int = 1,
    customization: Optional[str] = None,
) -> Dict[str, Any]:
    """驗證必填 + 解析別名 + 組裝飲料購物車品項 dict（不含 item_id）"""
    missing: List[str] = []
    if not flavor:
        missing.append("flavor")
    if not size:
        missing.append("size")
    if not temp:
        missing.append("temp")
    if missing:
        parts: List[str] = []
        if "flavor" in missing:
            parts.append("飲料品項")
        if "size" in missing or "temp" in missing:
            parts.append("規格（中冰/中溫/大冰/大溫）")
        return {"ok": False, "missing": missing, "message": f"請問{' 和 '.join(parts)}？"}
    resolved_flavor = resolve_flavor(flavor)
    resolved_size = resolve_size(size)
    resolved_temp = resolve_temp(temp)
    item: Dict[str, Any] = {
        "itemtype": "drink",
        "drink": resolved_flavor,
        "size": resolved_size,
        "temp": resolved_temp,
        "quantity": max(1, quantity),
    }
    if customization:
        item["customization"] = customization
    return {
        "ok": True,
        "item": item,
        "display_name": f"{resolved_size}{resolved_temp}{resolved_flavor}",
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
