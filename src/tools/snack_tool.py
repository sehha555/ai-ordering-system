import re
from typing import Dict, List, Optional, Any

from src.tools.menu import menu_price_service
from src.tools.riceball_tool import _chinese_number_to_int

# Define aliases to handle variations in user requests
SNACK_ALIASES = {
    "煎餃": "煎餃(8顆)",
    "蘿蔔糕": "港式蘿蔔糕",
    "港式蘿蔔糕": "港式蘿蔔糕",
    "韭菜餡餅": "韭菜餡餅(5顆)",
    "餡餅": "韭菜餡餅(5顆)",
    "荷包蛋": "荷包蛋",
    "蛋": "荷包蛋",
    "蔥蛋": "蔥蛋",
    "熱狗": "熱狗(3條)",
    "薯餅": "薯餅(1片)",
    "醬燒肉片": "醬燒肉片(1份)",
    "肉片": "醬燒肉片(1份)",
    "麥克雞塊": "麥克雞塊(5個)",
    "雞塊": "麥克雞塊(5個)",
    "香酥脆薯": "香酥脆薯",
    "薯條": "香酥脆薯",
    "原味卡啦雞腿": "原味咔啦雞腿",
    "卡啦雞": "原味咔啦雞腿",
    "無骨雞排": "無骨雞排",
    "雞排": "無骨雞排"
}


class SnackTool:
    def __init__(self):
        self.menu_items = [item for item in menu_price_service.get_raw_menu() if item['category'] == '點心']
        self.snack_names = sorted([item['name'] for item in self.menu_items], key=len, reverse=True)
        self.snack_keywords = sorted(list(SNACK_ALIASES.keys()), key=len, reverse=True)
        # Sort aliases by length for longest-match-first
        self.sorted_aliases = sorted(SNACK_ALIASES.items(), key=lambda x: len(x[0]), reverse=True)

    def parse_snack_utterance(self, text: str) -> Dict[str, Any]:
        """Parses the user's utterance to identify snack, quantity, and options."""
        snack = self.detect_snack(text)
        quantity = self.parse_quantity(text)
        
        # Parse options
        egg_cook = "全熟"  # Default
        if "半熟" in text:
            egg_cook = "半熟"
        
        no_pepper = False
        if snack in ["麥克雞塊(5個)", "香酥脆薯"] and ("不要胡椒" in text or "無椒" in text):
            no_pepper = True

        frame = {
            "itemtype": "snack",
            "snack": snack,
            "quantity": quantity,
            "egg_cook": egg_cook if snack == "荷包蛋" else None,
            "no_pepper": no_pepper,
            "raw_text": text,
            "missing_slots": []
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

    def quote_snack_price(self, frame: Dict[str, Any]) -> Dict[str, Any]:
        """Calculates the price for the given snack frame and adds notes."""
        snack_name = frame.get("snack")
        quantity = frame.get("quantity", 1)

        if not snack_name:
            return {"status": "error", "message": "缺少點心名稱，無法計價。"}

        try:
            base_price = menu_price_service.get_price("點心", snack_name)
            total_price = base_price * quantity
            
            message = f"{quantity}份{snack_name}，共 {total_price}元"

            return {
                "status": "success",
                "snack": snack_name,
                "quantity": quantity,
                "single_price": base_price,
                "total_price": total_price,
                "message": message,
            }
        except KeyError:
            return {"status": "error", "message": f"找不到點心品項：{snack_name}，無法計價。"}
        except RuntimeError as e:
            raise e


# Global instance
snack_tool = SnackTool()
