import re
from typing import Any, Dict, List, Optional, Tuple

from src.tools.menu import menu_price_service
from src.tools.riceball_tool import INGREDIENT_SYNONYMS, menu_tool as riceball_menu_tool

CARRIERS = ("吐司", "漢堡", "饅頭")

QUANTITY_MAP = {
    "零": 0,
    "一": 1,
    "二": 2,
    "兩": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


def _dedupe_keep_order(xs: List[str]) -> List[str]:
    return list(dict.fromkeys(xs or []))


def _chinese_number_to_int(token: str) -> Optional[int]:
    t = (token or "").strip()
    if not t:
        return None
    if t in QUANTITY_MAP and t != "十":
        return QUANTITY_MAP[t]
    if "十" in t:
        if t == "十":
            return 10
        parts = t.split("十")
        left = parts[0].strip()
        right = parts[1].strip() if len(parts) > 1 else ""
        tens = 1 if left == "" else QUANTITY_MAP.get(left)
        if tens is None:
            return None
        ones = 0 if right == "" else QUANTITY_MAP.get(right)
        if ones is None:
            return None
        return tens * 10 + ones
    return None


class CarrierTool:
    """
    共用載體品項工具：吐司/漢堡/饅頭
    - 支援 XX蛋 但未說載體 => 缺 carrier 反問
    - 支援 饅頭夾蛋加肉/加肉鬆 => 推回菜單 canonical flavor
    - 加料/去料 parsing 沿用飯糰規則（ingredients_add / ingredients_remove），價表也沿用 riceball_menu_tool.ADDON_PRICE_TABLE
    """

    EXTRA_SYNONYMS = {
        # 這些不是飯糰的同義詞，但載體品項常用
        "小黃瓜": "小黃瓜",
        "洋蔥": "洋蔥",
        "番茄醬": "番茄醬",
        "沙拉醬": "沙拉醬",
        "肉鬆": "肉鬆",
        "肉片": "肉片",
        "豬肉": "豬肉",
        "燒肉": "燒肉",
        "蜜汁": "蜜汁",
        "沙茶": "沙茶",
        "黑椒": "黑椒",
        "薯餅": "薯餅",
        "鮪魚": "鮪魚",
        "火腿": "火腿",
        "培根": "培根",
        "起司": "起司",
        "雞絲": "雞絲",
        "咔啦雞": "咔啦雞",
        "蔥蛋": "蔥蛋",
        "荷包蛋": "荷包蛋",
        "散蛋": "散蛋",
    }

    def __init__(self):
        self.menu_items = self._load_menu()
        self.price_index = self._build_price_index(self.menu_items)
        self.flavors_by_carrier = self._build_flavors_by_carrier(self.price_index)
        self.global_flavor_set = set(flavor for (_, flavor) in self.price_index.keys())

    # ---------- public ----------
    def parse_carrier_utterance(self, text: str) -> Dict[str, Any]:
        original = text or ""
        t = (text or "").strip()

        qty = self._parse_quantity(t)
        carrier = self._detect_carrier(t)  # may be None

        egg_style = self._detect_egg_style(t, carrier)

        # 先直接抓菜單 flavor（能命中就命中）
        flavor = self._detect_flavor_from_menu(t, carrier)

        ingredients_mode, only_ingredients = self._parse_only_mode(t)
        add_ingredients, remove_ingredients = self._parse_add_remove(t)

        # 若沒講 flavor，但講了「饅頭夾蛋/饅頭加蛋 + 加料」，就用加料推回 canonical
        if flavor is None and carrier == "饅頭":
            inferred = self._infer_mantou_flavor(t, add_ingredients)
            if inferred:
                flavor = inferred
                # 被用來推回口味的加料不應再算加料
                add_ingredients = self._remove_inference_addons(add_ingredients)

        # 再補一次：若仍缺 flavor，但 text 中有 "夾蛋" 且有饅頭 => 用菜單的「饅頭夾蛋」當 base
        if flavor is None and carrier == "饅頭" and ("夾蛋" in t or "加蛋" in t):
            if ("饅頭", "饅頭夾蛋") in self.price_index:
                flavor = "饅頭夾蛋"

        missing: List[str] = [] # DialogueManager will recompute missing slots

        frame: Dict[str, Any] = {
            "itemtype": "carrier", # Explicitly set itemtype
            "carrier": carrier,  # 吐司/漢堡/饅頭
            "flavor": flavor,    # e.g. 豬肉蛋 / 醬燒肉片蛋 / 饅頭夾蛋
            "quantity": qty,
            "egg_style": egg_style,  # 吐司/漢堡預設荷包蛋；饅頭預設蔥蛋
            "ingredients_mode": ingredients_mode,  # default/only
            "ingredients_only": only_ingredients,
            "ingredients_add": add_ingredients,
            "ingredients_remove": remove_ingredients,
            "ingredients": [],  # finalize_frame 會補齊
            "raw_text": original,
        }

        return self.finalize_frame(frame)

    def finalize_frame(self, frame: Dict[str, Any]) -> Dict[str, Any]:
        carrier = frame.get("carrier")
        flavor = frame.get("flavor")
        egg_style = frame.get("egg_style")

        if not carrier or not flavor:
            frame["ingredients"] = []
            return frame

        # default egg style
        if not egg_style:
            egg_style = self._default_egg_style(carrier)
            frame["egg_style"] = egg_style

        # base ingredients
        if carrier == "吐司":
            base = [flavor, "小黃瓜", egg_style or "荷包蛋", "沙拉醬"]
        elif carrier == "漢堡":
            base = [flavor, "小黃瓜", "洋蔥", egg_style or "荷包蛋", "番茄醬", "沙拉醬"]
        else:  # 饅頭
            base = [flavor, egg_style or "蔥蛋"]

        # only-mode：只保留指定配料（但不觸發 price_confirm）
        mode = frame.get("ingredients_mode") or "default"
        only_ings = frame.get("ingredients_only") or []
        if mode == "only":
            base = [self._normalize_ingredient(x) for x in only_ings if x]

        # remove
        removes = [self._normalize_ingredient(x) for x in (frame.get("ingredients_remove") or [])]
        base = [x for x in base if x not in set(removes)]

        # add
        adds = [self._normalize_ingredient(x) for x in (frame.get("ingredients_add") or [])]
        base = base + [x for x in adds if x]

        frame["ingredients"] = _dedupe_keep_order(base)
        return frame

    def quote_carrier_price(self, frame: Dict[str, Any]) -> Dict[str, Any]:
        carrier = frame.get("carrier")
        flavor = frame.get("flavor")

        if not carrier or not flavor:
            return {"status": "error", "message": "缺少 carrier 或 flavor，無法計價。"}

        base_price = self.price_index.get((carrier, flavor))
        if base_price is None:
            return {"status": "error", "message": f"找不到菜單品項：{flavor}{carrier}"}

        # 加料價表沿用飯糰 ADDON_PRICE_TABLE
        addon_total = 0
        unknown_add: List[str] = []
        for raw in (frame.get("ingredients_add") or []):
            key = self._normalize_ingredient(raw)
            # 推回口味後，不再把「肉/肉片/肉鬆」當作加料收費（避免雙算）
            if flavor and key and key in flavor:
                continue

            if key in riceball_menu_tool.ADDON_PRICE_TABLE:
                addon_total += int(riceball_menu_tool.ADDON_PRICE_TABLE[key])
            else:
                unknown_add.append(key)

        single_total = int(base_price) + int(addon_total)

        return {
            "status": "success",
            "carrier": carrier,
            "flavor": flavor,
            "base_price": int(base_price),
            "addon_total": int(addon_total),
            "unknown_add": unknown_add,
            "needs_store_confirm": len(unknown_add) > 0,
            "single_total": single_total,
            "message": f"{flavor}{carrier} 基礎{base_price} + 加料{addon_total} = {single_total}元",
        }

    # ---------- internal ----------
    def _load_menu(self) -> List[Dict[str, Any]]:
        return menu_price_service.get_raw_menu()

    def _build_price_index(self, items: List[Dict[str, Any]]) -> Dict[Tuple[str, str], int]:
        out: Dict[Tuple[str, str], int] = {}
        for it in items:
            cat = it.get("category")
            name = it.get("name", "")
            price = it.get("price")
            if cat not in CARRIERS:
                continue
            if not isinstance(price, int):
                continue
            if not isinstance(name, str) or not name.endswith(cat):
                continue
            flavor = name[: -len(cat)].strip()
            if flavor:
                out[(cat, flavor)] = int(price)
        return out

    def _build_flavors_by_carrier(self, index: Dict[Tuple[str, str], int]) -> Dict[str, List[str]]:
        out: Dict[str, List[str]] = {c: [] for c in CARRIERS}
        for (c, f) in index.keys():
            out[c].append(f)
        for c in CARRIERS:
            out[c] = sorted(out[c], key=len, reverse=True)
        return out

    def _detect_carrier(self, text: str) -> Optional[str]:
        for c in CARRIERS:
            if c in text:
                return c
        return None

    def _default_egg_style(self, carrier: str) -> str:
        return "蔥蛋" if carrier == "饅頭" else "荷包蛋"

    def _detect_egg_style(self, text: str, carrier: Optional[str]) -> str:
        t = text
        # 明確指定（含「換」）
        if "荷包" in t:
            return "荷包蛋"
        if "散蛋" in t or "炒蛋" in t:
            return "散蛋"
        if "蔥蛋" in t or "葱蛋" in t:
            return "蔥蛋"
        # 不指定就用預設
        if carrier:
            return self._default_egg_style(carrier)
        # carrier 未知時：先不強制（等補 carrier 後 finalize）
        return ""

    def _detect_flavor_from_menu(self, text: str, carrier: Optional[str]) -> Optional[str]:
        t = text

        # 1) 若有 carrier：只在該 carrier 的 flavor 裡找
        if carrier in self.flavors_by_carrier:
            for f in self.flavors_by_carrier[carrier]:
                if f and f in t:
                    return f
            return None

        # 2) 沒 carrier：用全域 flavor 找（支援「我要一個豬肉蛋」）
        for f in sorted(self.global_flavor_set, key=len, reverse=True):
            if f and f in t:
                return f

        return None

    def _parse_quantity(self, text: str) -> int:
        t = text
        m = re.search(r"(\d{1,2})\s*(顆|個)", t)
        if m:
            q = int(m.group(1))
            return q if q > 0 else 1
        m2 = re.search(r"([零一二兩三四五六七八九十]{1,3})\s*(顆|個)", t)
        if m2:
            v = _chinese_number_to_int(m2.group(1))
            return v if isinstance(v, int) and v > 0 else 1
        return 1

    def _normalize_ingredient(self, raw: str) -> str:
        if not raw:
            return ""
        # 先用飯糰 synonyms，再補載體 extras
        x = INGREDIENT_SYNONYMS.get(raw, raw)
        return self.EXTRA_SYNONYMS.get(x, x)

    def _parse_only_mode(self, text: str) -> Tuple[str, List[str]]:
        t = text
        m = re.search(r"只要(.+)", t)
        if not m:
            return "default", []
        only_part = m.group(1).strip()
        if not only_part:
            return "only", []
        candidates = set()
        for k in set(list(INGREDIENT_SYNONYMS.keys()) + list(self.EXTRA_SYNONYMS.keys())):
            if len(k) >= 2:
                candidates.add(k)
        only_ings: List[str] = []
        for c in sorted(candidates, key=len, reverse=True):
            if c and c in only_part:
                only_ings.append(self._normalize_ingredient(c))
        return "only", _dedupe_keep_order(only_ings)

    def _parse_add_remove(self, text: str) -> Tuple[List[str], List[str]]:
        t = text
        adds: List[str] = []
        removes: List[str] = []

        # 特例：客人常說「加肉」= 肉片類（後續會推回口味）
        if "加肉鬆" in t or "再加肉鬆" in t:
            adds.append("肉鬆")
        elif "加肉片" in t or "再加肉片" in t:
            adds.append("肉片")
        elif "加肉" in t or "再加肉" in t:
            adds.append("肉")

        # 一般規則：加X / 再加X
        for syn in sorted(set(list(INGREDIENT_SYNONYMS.keys()) + list(self.EXTRA_SYNONYMS.keys())), key=len, reverse=True):
            if syn in ("加蛋", "蛋"):  # 這裡不把「加蛋」當作加料，避免雙意義；載體品項蛋是內建
                continue
            if ("加" + syn) in t or ("再加" + syn) in t:
                adds.append(self._normalize_ingredient(syn))

        # 去料：不要/去掉/拿掉/不加X
        for syn in sorted(set(list(INGREDIENT_SYNONYMS.keys()) + list(self.EXTRA_SYNONYMS.keys())), key=len, reverse=True):
            if ("不要" + syn) in t or ("去掉" + syn) in t or ("拿掉" + syn) in t or ("不加" + syn) in t:
                removes.append(self._normalize_ingredient(syn))

        adds = _dedupe_keep_order([self._normalize_ingredient(x) for x in adds if x])
        removes = _dedupe_keep_order([self._normalize_ingredient(x) for x in removes if x])
        return adds, removes

    def _infer_mantou_flavor(self, text: str, add_ingredients: List[str]) -> Optional[str]:
        t = text
        adds = set([self._normalize_ingredient(x) for x in (add_ingredients or [])])

        # 口語「加肉」的判斷：同時看句子有沒有黑椒/沙茶/蜜汁
        if ("肉" in adds) or ("肉片" in adds) or ("肉片" in t) or ("加肉" in t):
            if "黑椒" in t and ("饅頭", "黑椒肉片蛋") in self.price_index:
                return "黑椒肉片蛋"
            if "沙茶" in t and ("饅頭", "沙茶豬肉蛋") in self.price_index:
                return "沙茶豬肉蛋"
            if "蜜汁" in t and ("饅頭", "蜜汁燒肉蛋") in self.price_index:
                return "蜜汁燒肉蛋"
            if ("饅頭", "醬燒肉片蛋") in self.price_index:
                return "醬燒肉片蛋"

        # 其他加料推回：肉鬆/火腿/起司/培根/鮪魚/薯餅
        mapping = [
            ("肉鬆", "肉鬆蛋"),
            ("火腿", "火腿蛋"),
            ("起司", "起司蛋"),
            ("培根", "培根蛋"),
            ("鮪魚", "鮪魚蛋"),
            ("薯餅", "薯餅蛋"),
        ]
        for key, flav in mapping:
            if key in adds and ("饅頭", flav) in self.price_index:
                return flav

        # 若講「豬肉」但沒講沙茶，店內只有「沙茶豬肉蛋」就先對齊它
        if ("豬肉" in t) and ("饅頭", "沙茶豬肉蛋") in self.price_index:
            return "沙茶豬肉蛋"

        return None

    def _remove_inference_addons(self, add_ingredients: List[str]) -> List[str]:
        # 推回口味後，不再把「肉/肉片/肉鬆」當作加料收費（避免雙算）
        drop = {"肉", "肉片", "肉鬆"}
        return [x for x in add_ingredients if self._normalize_ingredient(x) not in drop]


carrier_tool = CarrierTool()

