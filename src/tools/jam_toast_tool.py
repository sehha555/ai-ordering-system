# -*- coding: utf-8 -*-
from typing import Dict, Optional, Any

from src.tools.menu import menu_price_service
from src.tools.text_utils import parse_quantity as _parse_quantity_util
from src.config.config_loader import load_json_config

_jt_cfg = load_json_config("aliases_jam_toast.json")
JAM_TOAST_FLAVORS = _jt_cfg["jam_toast_flavors"]
SIZE_MAP = _jt_cfg["size_map"]

class JamToastTool:
    def parse_jam_toast_utterance(self, text: str) -> Dict[str, Any]:
        """
        Parses the user's utterance to identify jam toast orders, including flavor,
        size, and customization options (no_toast, cut_edge).
        """
        flavor = self._detect_flavor(text)
        size = self._detect_size(text)
        quantity = self._parse_quantity(text)
        no_toast = "不烤" in text
        cut_edge = "切邊" in text

        # 業務規則：切邊僅限 cut_edge_only_size
        if cut_edge and size != _jt_cfg["cut_edge_only_size"]:
            return {
                "ok": False,
                "message": "不好意思，只有厚片才能切邊喔！",
                "itemtype": "jam_toast",
                "jam_toast": None,
                "quantity": quantity,
                "no_toast": no_toast,
                "cut_edge": cut_edge,
                "missing_slots": ["size"]
            }

        full_name = None
        missing_slots = []
        if flavor and size:
            full_name = f"果醬吐司({flavor}/{size})"
        elif flavor and not size:
            # 未指定 size 時套用預設值
            size = _jt_cfg["default_size"]
            full_name = f"果醬吐司({flavor}/{size})"

        if not flavor: missing_slots.append("flavor")
        if not size: missing_slots.append("size")


        frame = {
            "itemtype": "jam_toast",
            "jam_toast": full_name,
            "flavor": flavor,
            "size": size,
            "quantity": quantity,
            "no_toast": no_toast,
            "cut_edge": cut_edge,
            "raw_text": text,
            "missing_slots": missing_slots,
            "ok": True
        }

        # If a valid item was constructed, check if it exists in the menu
        if full_name:
            try:
                # This will throw a KeyError if not found
                menu_price_service.get_price("果醬吐司", full_name)
            except (KeyError, RuntimeError):
                frame["jam_toast"] = None
                if "flavor" not in missing_slots: missing_slots.append("flavor") # Re-add as missing
                if "size" not in missing_slots: missing_slots.append("size")

        return frame

    def quote_jam_toast_price(self, frame: Dict[str, Any]) -> Dict[str, Any]:
        """Calculates the price for the given jam toast frame."""
        jam_toast_name = frame.get("jam_toast")
        quantity = frame.get("quantity", 1)

        if not jam_toast_name:
            return {"ok": False, "message": "缺少果醬吐司品名，無法計價。"}

        try:
            base_price = menu_price_service.get_price("果醬吐司", jam_toast_name)
            total_price = base_price * quantity

            return {
                "ok": True,
                "jam_toast": jam_toast_name,
                "quantity": quantity,
                "single_price": base_price,
                "total_price": total_price,
                "message": f"{quantity}份{jam_toast_name}，共 {total_price}元",
            }
        except KeyError:
            return {"ok": False, "message": f"找不到品項：{jam_toast_name}，無法計價。"}
        except RuntimeError as e:
            raise e

    def _detect_flavor(self, text: str) -> Optional[str]:
        for flavor in JAM_TOAST_FLAVORS:
            if flavor in text:
                return flavor
        return None

    def _detect_size(self, text: str) -> Optional[str]:
        # Prioritize longer matches like "薄片" over "吐司"
        sorted_sizes = sorted(SIZE_MAP.keys(), key=len, reverse=True)
        for size_key in sorted_sizes:
            if size_key in text:
                return SIZE_MAP[size_key]
        return None

    def _parse_quantity(self, text: str) -> int:
        """Parses quantity from the utterance."""
        return _parse_quantity_util(text, units=("份", "個"))

# Global instance
jam_toast_tool = JamToastTool()
