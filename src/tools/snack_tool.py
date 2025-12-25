from typing import Dict, Any, List, Optional


class SnackTool:
    # menu_all.json 明列點心：醬燒肉片(1份) 35 元 [file:110]
    SNACK_PRICES = {
        "醬燒肉片(1份)": 35,
    }

    # 明列品項同義詞（客人簡稱）
    SNACK_ALIASES = {
        "醬燒肉片": "醬燒肉片(1份)",
        "肉片": "醬燒肉片(1份)",
    }

    # 隱藏規則：多數肉類單點(1份) 統一 35
    HIDDEN_MEAT_UNIT_PRICE = 35

    # 你提到常見的（可再擴充）
    HIDDEN_MEAT_KEYS = {
        "雞絲": "雞絲",
        "鮪魚": "鮪魚",
        "雞排": "雞排",
        "豬肉": "豬肉",
        "培根": "培根",
        "火腿": "火腿",
        "肉鬆": "肉鬆",
        # 肉片已經被明列映射處理
    }

    # 哪些單點建議問「要不要跟主餐裝一起」
    # 你說蛋類/肉片/雞排等都可以問，這裡先把肉類類型都視為 True
    def parse_snack_utterance(self, text: str) -> Dict[str, Any]:
        t = text.strip()

        qty = self._parse_quantity(t)

        item, is_hidden = self._detect_item_or_hidden_meat(t)

        missing_slots: List[str] = []
        if not item:
            missing_slots.append("item")

        packable = True if item else False
        suggest_pack_with_main = True if item else False

        return {
            "item_type": "snack",
            "item_name": item,
            "quantity": qty,
            "is_hidden_item": is_hidden,
            "packable": packable,
            "suggest_pack_with_main": suggest_pack_with_main,
            "missing_slots": missing_slots,
            "raw_text": text,
        }

    def quote_snack_price(self, frame: Dict[str, Any]) -> Dict[str, Any]:
        item = frame.get("item_name")
        qty = frame.get("quantity", 1)
        is_hidden = frame.get("is_hidden_item", False)

        if not item:
            return {
                "status": "error",
                "message": "找不到此單點品項，請再確認一次。",
                "item_name": item,
                "quantity": qty,
            }

        if item in self.SNACK_PRICES:
            single = self.SNACK_PRICES[item]
        elif is_hidden:
            single = self.HIDDEN_MEAT_UNIT_PRICE
        else:
            return {
                "status": "error",
                "message": "找不到此單點品項，請再確認一次。",
                "item_name": item,
                "quantity": qty,
            }

        total = single * qty
        hidden_note = "（隱藏單點）" if is_hidden else ""

        return {
            "status": "success",
            "item_name": item,
            "quantity": qty,
            "single_price": single,
            "total_price": total,
            "is_hidden_item": is_hidden,
            "message": f"{qty}份{item}{hidden_note}，共 {total}元",
        }

    def _detect_item_or_hidden_meat(self, text: str) -> (Optional[str], bool):
        # 1) 先吃明列品項（肉片/醬燒肉片）
        keys = sorted(self.SNACK_ALIASES.keys(), key=len, reverse=True)
        for k in keys:
            if k in text:
                return self.SNACK_ALIASES[k], False

        # 2) 再走隱藏規則：抓到肉類關鍵字就給「{key}(1份)」
        for k, canon in self.HIDDEN_MEAT_KEYS.items():
            if k in text:
                return f"{canon}(1份)", True

        return None, False

    def _parse_quantity(self, text: str) -> int:
        # 單點通常一份，但支援「兩份雞絲」這種
        zh_map = {"一": 1, "二": 2, "兩": 2, "三": 3, "四": 4, "五": 5}
        m = __import__("re").search(r"(\\d+)\\s*份", text)
        if m:
            return int(m.group(1))
        m2 = __import__("re").search(r"([一二兩三四五])\\s*份", text)
        if m2:
            return zh_map.get(m2.group(1), 1)
        return 1


snack_tool = SnackTool()


if __name__ == "__main__":
    tests = [
        "我要單點一份肉片",
        "來一份醬燒肉片",
        "單點一份雞絲",
        "單點兩份鮪魚",
        "單點一份雞排",
    ]
    for t in tests:
        frame = snack_tool.parse_snack_utterance(t)
        quote = snack_tool.quote_snack_price(frame)
        print(f"「{t}」→ {quote.get('message')}")