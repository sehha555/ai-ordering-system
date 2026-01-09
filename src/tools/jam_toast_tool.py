# -*- coding: utf-8 -*-
import re
from typing import Dict, List, Optional, Any

from src.tools.menu import menu_price_service
from src.tools.riceball_tool import _chinese_number_to_int

JAM_TOAST_FLAVORS = ["草莓", "花生", "蒜香", "奶酥", "巧克力"]
SIZE_MAP = {"薄片": "薄片", "厚片": "厚片", "吐司": "薄片"}

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

        # Business rule: cut_edge is only for 厚片
        if cut_edge and size != "厚片":
            return {
                "status": "error",
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
            # Default "吐司" to "薄片"
            size = "薄片"
            full_name = f"果醬吐司({flavor}/{size})"
        
        if not flavor: missing_slots.append("flavor")
        if not size: missing_slots.append("size")


        frame = {
            "itemtype": "jam_toast",
            "jam_toast": full_name,
            "quantity": quantity,
            "no_toast": no_toast,
            "cut_edge": cut_edge,
            "raw_text": text,
            "missing_slots": missing_slots,
            "status": "success"
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
            return {"status": "error", "message": "缺少果醬吐司品名，無法計價。"}

        try:
            base_price = menu_price_service.get_price("果醬吐司", jam_toast_name)
            total_price = base_price * quantity

            return {
                "status": "success",
                "jam_toast": jam_toast_name,
                "quantity": quantity,
                "single_price": base_price,
                "total_price": total_price,
                "message": f"{quantity}份{jam_toast_name}，共 {total_price}元",
            }
        except KeyError:
            return {"status": "error", "message": f"找不到品項：{jam_toast_name}，無法計價。"}
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
        if "一份" in text or "來一份" in text:
            return 1
        m = re.search(r'(\d+)\s*(份|個)', text)
        if m:
            return int(m.group(1))
        m_cn = re.search(r'([一二兩三四五六七八九十]{1,3})\s*(份|個)', text)
        if m_cn:
            val = _chinese_number_to_int(m_cn.group(1))
            if val is not None:
                return val
        return 1

# Global instance
jam_toast_tool = JamToastTool()
