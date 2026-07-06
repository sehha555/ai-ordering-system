from typing import Dict, Optional, Any

from src.config.config_loader import load_json_config
from src.tools.menu import menu_price_service
from src.tools.text_utils import parse_quantity as _parse_quantity_util

# 從 aliases_snack.json 載入別名常數
_snack_cfg = load_json_config("aliases_snack.json")
SNACK_ALIASES: Dict[str, str] = _snack_cfg["snack_aliases"]
_DEFAULT_EGG_COOK: str = _snack_cfg["default_egg_cook"]
_PEPPER_RESTRICTED_ITEMS: list = _snack_cfg["pepper_restricted_items"]

_ALIASES_SORTED = tuple(sorted(SNACK_ALIASES.keys(), key=len, reverse=True))


def resolve_flavor(flavor: Optional[str], menu_names: Optional[set] = None) -> Optional[str]:
    """點心別名 → 標準菜單名；已是菜單名則跳過，避免子串誤匹配。
    短 alias（<2 字元）不做結尾匹配，避免「起司蛋」匹配「荷包蛋」。
    """
    if not flavor:
        return None
    if menu_names and flavor in menu_names:
        return flavor
    for alias in _ALIASES_SORTED:
        if alias == flavor:
            return SNACK_ALIASES[alias]
        if len(alias) >= 2 and flavor.endswith(alias):
            return SNACK_ALIASES[alias]
    return None


def build_cart_item(
    flavor: Optional[str] = None,
    quantity: int = 1,
    customization: Optional[str] = None,
) -> Dict[str, Any]:
    """組裝點心購物車品項 dict（不含 item_id）。flavor 應為已解析的菜單名。"""
    if not flavor:
        return {"ok": False, "missing": ["flavor"], "message": "請問要什麼點心？"}
    item: Dict[str, Any] = {
        "itemtype": "snack",
        "snack": flavor,
        "quantity": max(1, quantity),
    }
    if customization:
        item["customization"] = customization
    return {"ok": True, "item": item, "display_name": flavor}


class SnackTool:
    def __init__(self):
        self.menu_items = [
            item for item in menu_price_service.get_raw_menu() if item["category"] == "點心"
        ]
        self.snack_names = sorted([item["name"] for item in self.menu_items], key=len, reverse=True)
        self.snack_keywords = sorted(list(SNACK_ALIASES.keys()), key=len, reverse=True)
        # Sort aliases by length for longest-match-first
        self.sorted_aliases = sorted(SNACK_ALIASES.items(), key=lambda x: len(x[0]), reverse=True)

    def parse_snack_utterance(self, text: str) -> Dict[str, Any]:
        """Parses the user's utterance to identify snack, quantity, and options."""
        snack = self.detect_snack(text)
        quantity = self.parse_quantity(text)

        # Parse options
        egg_cook = _DEFAULT_EGG_COOK  # 預設蛋熟度，從 config 載入
        if "半熟" in text:
            egg_cook = "半熟"

        no_pepper = False
        if snack in _PEPPER_RESTRICTED_ITEMS and ("不要胡椒" in text or "無椒" in text):
            no_pepper = True

        frame = {
            "itemtype": "snack",
            "snack": snack,
            "quantity": quantity,
            "egg_cook": egg_cook if snack == "荷包蛋" else None,
            "no_pepper": no_pepper,
            "raw_text": text,
            "missing_slots": [],
        }

        if not snack:
            frame["missing_slots"].append("snack")

        return frame

    def detect_snack(self, text: str) -> Optional[str]:
        """Detects the snack item from the text, prioritizing longer alias matches."""
        # 1. Longest alias match first
        for alias, canonical_name in self.sorted_aliases:
            if alias in text:
                return canonical_name

        # 2. Fallback to full menu name matching (less likely to be used)
        for snack_name in self.snack_names:
            if snack_name in text:
                return snack_name
        return None

    def parse_quantity(self, text: str) -> int:
        """Parses the quantity from the utterance."""
        return _parse_quantity_util(text, units=("份", "個"))

    def quote_snack_price(self, frame: Dict[str, Any]) -> Dict[str, Any]:
        """Calculates the price for the given snack frame and adds notes."""
        snack_name = frame.get("snack")
        quantity = frame.get("quantity", 1)

        if not snack_name:
            return {"ok": False, "message": "缺少點心名稱，無法計價。"}

        try:
            # add_item 將點心/鐵板麵/蔥抓餅三個菜單分類都歸入 snack，計價需依序查
            base_price = None
            for category in ("點心", "鐵板麵", "蔥抓餅"):
                try:
                    base_price = menu_price_service.get_price(category, snack_name)
                    break
                except KeyError:
                    continue
            if base_price is None:
                raise KeyError(snack_name)
            total_price = base_price * quantity

            message = f"{quantity}份{snack_name}，共 {total_price}元"

            return {
                "ok": True,
                "snack": snack_name,
                "quantity": quantity,
                "single_price": base_price,
                "total_price": total_price,
                "message": message,
            }
        except KeyError:
            return {"ok": False, "message": f"找不到點心品項：{snack_name}，無法計價。"}
        except RuntimeError as e:
            raise e


# Global instance
snack_tool = SnackTool()
