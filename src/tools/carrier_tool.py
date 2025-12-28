import re
import json
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

MENUFILE = Path(__file__).parent / "menu" / "menu_all.json"


class CarrierTool:
    CARRIERS = ("吐司", "漢堡", "饅頭")

    # 口味命名尾綴（把 carrier 去掉後，剩下視為 flavor）
    SUFFIXES = ("吐司", "漢堡", "饅頭")

    def __init__(self):
        self.menu_items = self._load_menu()
        self.price_index = self._build_price_index(self.menu_items)
        self.flavor_set = self._build_flavor_set(self.price_index)

    def parse_carrier_utterance(self, text: str) -> Dict[str, Any]:
        t = (text or "").strip()
        qty = self._parse_quantity(t)

        carrier = self._detect_carrier(t)  # 可能 None
        egg_style = self._detect_egg_style(t)  # 只對饅頭有意義，但先都解析

        flavor = self._detect_flavor(t)  # 可能 None（完全沒對到菜單）

        missing: List[str] = []
        if flavor is None:
            missing.append("flavor")
        if carrier is None:
            missing.append("carrier")

        frame: Dict[str, Any] = {
            "item_type": "carrier_item",
            "quantity": qty,
            "carrier": carrier,          # "吐司"/"漢堡"/"饅頭"/None
            "flavor": flavor,            # e.g. "豬肉蛋"
            "egg_style": egg_style,      # "蔥蛋"(default)/"荷包蛋"/"散蛋"
            "ingredients": self._build_default_ingredients(carrier, flavor, egg_style),
            "missing_slots": missing,
            "raw_text": t,
        }

        return frame

    def quote_carrier_price(self, frame: Dict[str, Any]) -> Dict[str, Any]:
        qty = int(frame.get("quantity") or 1)
        qty = qty if qty > 0 else 1
        carrier = frame.get("carrier")
        flavor = frame.get("flavor")

        if not carrier or not flavor:
            return {"status": "error", "message": "缺少 carrier 或 flavor，無法計價。"}

        price = self.price_index.get((carrier, flavor))
        if price is None:
            return {"status": "error", "message": f"找不到價格：{flavor}{carrier}"}

        total = int(price) * qty
        return {
            "status": "success",
            "quantity": qty,
            "carrier": carrier,
            "flavor": flavor,
            "single_price": int(price),
            "total_price": total,
            "message": f"{qty}個{flavor}{carrier}，共 {total}元",
        }

    # ---------- helpers ----------
    def _load_menu(self) -> List[Dict[str, Any]]:
        try:
            with open(MENUFILE, "r", encoding="utf-8-sig") as f:
                return json.load(f)
        except FileNotFoundError:
            return []

    def _build_price_index(self, items: List[Dict[str, Any]]) -> Dict[Tuple[str, str], int]:
        out: Dict[Tuple[str, str], int] = {}
        for it in items:
            cat = it.get("category")
            name = it.get("name", "")
            price = it.get("price")
            if cat not in self.CARRIERS:
                continue
            if not isinstance(price, int):
                continue
            flavor = self._name_to_flavor(name, cat)
            if flavor:
                out[(cat, flavor)] = price
        return out

    def _build_flavor_set(self, price_index: Dict[Tuple[str, str], int]) -> set:
        return set(flavor for (_, flavor) in price_index.keys())

    def _name_to_flavor(self, name: str, carrier: str) -> Optional[str]:
        if not name.endswith(carrier):
            return None
        return name[: -len(carrier)].strip() or None

    def _detect_carrier(self, text: str) -> Optional[str]:
        for c in self.CARRIERS:
            if c in text:
                return c
        return None

    def _detect_flavor(self, text: str) -> Optional[str]:
        # 1) 先嘗試直接命中「菜單完整品名」：例如 "豬肉蛋吐司"
        for c in self.CARRIERS:
            if c in text:
                # 若使用者講了載體，就只在該載體下找 flavor
                candidates = [f for (cc, f) in self.price_index.keys() if cc == c]
                candidates = sorted(candidates, key=len, reverse=True)
                for f in candidates:
                    if f in text:
                        return f
                # 若沒命中，可能說 "豬肉蛋" + "吐司" 分開，仍可回傳 None 讓 DM 問 flavor
                return None

        # 2) 沒講載體：用 flavor_set 去掃（這就是 "我要一個豬肉蛋" 的核心）
        candidates = sorted(self.flavor_set, key=len, reverse=True)
        for f in candidates:
            if f in text:
                return f

        return None

    def _detect_egg_style(self, text: str) -> str:
        t = text
        if "荷包" in t:
            return "荷包蛋"
        if "散蛋" in t or "炒蛋" in t:
            return "散蛋"
        return "蔥蛋"

    def _build_default_ingredients(self, carrier: Optional[str], flavor: Optional[str], egg_style: str) -> List[str]:
        if not carrier or not flavor:
            return []

        if carrier == "吐司":
            # 你指定：口味主體 + 小黃瓜 + 荷包蛋 + 沙拉醬
            return [flavor, "小黃瓜", "荷包蛋", "沙拉醬"]

        if carrier == "漢堡":
            # 你指定：口味主體 + 小黃瓜 + 洋蔥 + 荷包蛋 + 番茄醬 + 沙拉醬
            return [flavor, "小黃瓜", "洋蔥", "荷包蛋", "番茄醬", "沙拉醬"]

        if carrier == "饅頭":
            # 你指定：口味 + 加一個蛋；預設蔥蛋，不多問
            # 若客人要求荷包/散蛋才替換
            return [flavor, egg_style]

        return []

    def _parse_quantity(self, text: str) -> int:
        zh_map = {"一": 1, "二": 2, "兩": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
        m = re.search(r"(\d+)\s*個?", text)
        if m:
            return max(1, int(m.group(1)))
        m2 = re.search(r"([一二兩三四五六七八九十])\s*個?", text)
        if m2:
            return max(1, zh_map.get(m2.group(1), 1))
        return 1


carrier_tool = CarrierTool()
