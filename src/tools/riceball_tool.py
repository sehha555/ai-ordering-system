"""
源飯糰工具 - 查詢、報價、配方、口語解析、加料加價
（維持 menu_tool 介面供 llm_service 使用）
"""

import re
import json
from typing import List, Dict, Any, Optional
from pathlib import Path

from src.config.config_loader import load_json_config
from src.tools.menu import menu_price_service

MENU_TOOL_VERSION = "2025-12-27-config-v6"

RECIPES_FILE = Path(__file__).parent / "menu" / "riceball_recipes.json"

# 飯糰價格規則
SPECIAL_FLAVORS_ONLY_LARGE = {"源味傳統", "素料", "甜飯糰", "半甜鹹"}  # 只有加大，沒有重量

HEAVY_RICEBALL_PRICES = {
    "醬燒里肌": 80,
    "黑椒里肌": 80,
    "蜜汁燒肉": 80,
    "沙茶豬肉": 80,
    "香燻培根": 80,
    "風味火腿": 80,
    "椒鹽雞絲": 80,
    "蒜香雞肉": 80,
    "咖哩嫩雞": 80,
    "和風雞肉": 80,
    "QQ滷蛋": 80,
    "懷古鹹蛋": 80,
    "蔥蛋豆芽": 80,
    "茄汁蛋包": 80,
    "韓式泡菜": 80,
    "香濃起司": 80,
    "香煎吻魚": 80,
    "鮪魚飯糰": 80,
    "甜心芋泥": 80,
}

# 口味別名（只保留必要映射）
# 重要：不要放 "甜" -> "甜飯糰"，避免 "半甜鹹" 被 "甜" 提前吃掉
FLAVOR_ALIASES: Dict[str, str] = {
    # 源味傳統相關
    "源味傳統": "源味傳統",
    "源味飯糰": "源味傳統",
    "傳統源味": "源味傳統",
    "源味": "源味傳統",
    "傳統飯糰": "源味傳統",
    "傳統": "源味傳統",
    # 甜/半甜
    "甜飯糰": "甜飯糰",
    "半甜鹹": "半甜鹹",
    # 注意：依你需求移除 `"半甜": "半甜鹹"`
    # 你指定的 alias（短詞 → 完整口味）
    "芋泥": "甜心芋泥",
    "沙茶": "沙茶豬肉",
    "咖哩": "咖哩嫩雞",
    "泡菜": "韓式泡菜",
    "滷蛋": "QQ滷蛋",
    "豆芽": "蔥蛋豆芽",
    "鹹蛋": "懷古鹹蛋",
    "鹹蛋飯糰": "懷古鹹蛋",
    "雞排": "嫩汁雞排",
    "火腿": "風味火腿",
    "培根": "香燻培根",
    "蜜汁": "蜜汁燒肉",
    "黑椒": "黑椒里肌",
    # 實務常用簡稱（避免「蒜香」被當成源味傳統）
    "蒜香": "蒜香雞肉",
    "和風": "和風雞肉",
    "椒鹽": "椒鹽雞絲",
}

# 米飯種類（全句解析只放「明確詞」；口語短詞請放 DM pending rice）
RICE_KEYWORDS = {
    "混合米": "混米",
    "混米": "混米",
    "紫飯": "紫米",
    "紫米": "紫米",
    "白飯": "白米",
    "白米": "白米",
}

# 數量（支援到 99：阿拉伯數字 + 中文數字）
QUANTITY_MAP = {"零": 0, "一": 1, "二": 2, "兩": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}

# 配料同義詞（normalize）
INGREDIENT_SYNONYMS = {
    "蛋": "蛋",
    "加蛋": "蛋",
    "起司片": "起司",
    "起司": "起司",
    "油條": "油條",
    # 注意：這裡的單字 "肉" 會造成子字串誤判，所以 only-mode 解析時會排除 len<2 的 synonym
    "肉": "肉類",
    "肉類": "肉類",
    "火腿": "火腿",
    "培根": "培根",
    "泡菜": "泡菜",
    "鹹蛋": "鹹蛋",
    "鮪魚沙拉": "鮪魚",
    "鮪魚": "鮪魚",
}

SPECIAL_ONLY_PATTERNS = [
    "只要飯跟蛋",
    "只要飯和蛋",
    "只要飯蛋",
    "只要飯",
    # 你可以在這裡繼續補口語變體
]

ORAL_RICEBALL_KEYWORDS = ["飯糰", "飯團"]


def _dedupe_keep_order(xs: List[str]) -> List[str]:
    return list(dict.fromkeys(xs or []))


def _chinese_number_to_int(token: str) -> Optional[int]:
    """
    支援 0~99 的中文數字（含：十、十五、二十、二十五、兩…）
    """
    t = (token or "").strip()
    if not t:
        return None

    # 常見：單字
    if t in QUANTITY_MAP and t != "十":
        return QUANTITY_MAP[t]

    # 十 / 十五 / 二十 / 二十五
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

    # 其他（例如「二三」這種不規範，直接不認）
    return None


class MenuTool:
    def __init__(self):
        self.menu_data = self._load_menu()
        self.recipes_data = self._load_recipes()

        cfg = load_json_config("addon_prices.json")
        self.ADDON_PRICE_TABLE = cfg.get("riceball_addons", {})

    def _load_menu(self) -> Dict[str, Any]:
        try:
            items = menu_price_service.get_raw_menu()
            return {"items": items}
        except RuntimeError:
            # If the service fails, return an empty structure to maintain behavior
            # for callers that expect a dict. The error will be caught upstream.
            return {"items": []}

    def _load_recipes(self) -> Dict[str, Any]:
        try:
            with open(RECIPES_FILE, "r", encoding="utf-8-sig") as f:
                return json.load(f)
        except FileNotFoundError:
            return {}

    def get_openai_tools_schema(self) -> List[Dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "quote_riceball_price",
                    "description": "計算飯糰基礎價格（加大+5，重量用重量飯糰價格；特殊口味只加大；加蛋+10）",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "flavor": {"type": "string"},
                            "large": {"type": "boolean"},
                            "heavy": {"type": "boolean"},
                            "extra_egg": {"type": "boolean"},
                        },
                        "required": ["flavor"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_riceball_recipe",
                    "description": "取得飯糰預設配料",
                    "parameters": {
                        "type": "object",
                        "properties": {"flavor": {"type": "string"}},
                        "required": ["flavor"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "parse_riceball_utterance",
                    "description": "解析客人點飯糰的一句話，輸出結構化訂單框架",
                    "parameters": {
                        "type": "object",
                        "properties": {"text": {"type": "string"}},
                        "required": ["text"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "quote_riceball_customization_price",
                    "description": "計算飯糰加料加價；若為極端客製（只要/剩極少配料），則回傳最低35且5元級距，要求人工選價",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "flavor": {"type": "string"},
                            "add_ingredients": {"type": "array", "items": {"type": "string"}},
                            "remove_ingredients": {"type": "array", "items": {"type": "string"}},
                            "only_ingredients": {"type": "array", "items": {"type": "string"}},
                            "only_mode": {"type": "boolean"},
                        },
                        "required": ["flavor"],
                    },
                },
            },
        ]

    def get_riceball_recipe(self, flavor: str) -> Dict[str, Any]:
        recipe = self.recipes_data.get(flavor, {})
        return {
            "status": "success" if recipe else "not_found",
            "flavor": flavor,
            "ingredients": recipe.get("ingredients", []),
            "available": bool(recipe),
        }

    def quote_riceball_price(
        self,
        flavor: str,
        large: bool = False,
        heavy: bool = False,
        extra_egg: bool = False,
    ) -> Dict[str, Any]:
        items = self.menu_data.get("items", [])
        base_item = None

        for item in items:
            if item.get("category") == "飯糰" and flavor in item.get("name", ""):
                base_item = item
                break

        if not base_item:
            return {"status": "error", "message": f"找不到 '{flavor}'", "needs_confirm": True}

        base_price = int(base_item.get("price", 0))
        total = base_price

        is_large = bool(large)
        is_heavy = bool(heavy)

        # 特殊口味不允許重量，若使用者說重量則轉成加大
        if flavor in SPECIAL_FLAVORS_ONLY_LARGE and is_heavy:
            is_large = True
            is_heavy = False

        if is_heavy:
            heavy_price = HEAVY_RICEBALL_PRICES.get(flavor)
            if heavy_price is None:
                return {
                    "status": "warning",
                    "flavor": flavor,
                    "total_price": None,
                    "needs_confirm": True,
                    "message": f"{flavor}重量版需店家確認價格",
                }
            total = int(heavy_price)
        else:
            if is_large:
                total += 5

        if extra_egg:
            total += 10

        return {
            "status": "success",
            "flavor": flavor,
            "base_price": base_price,
            "large": is_large,
            "heavy": is_heavy,
            "extra_egg": bool(extra_egg),
            "total_price": total,
            "needs_confirm": False,
            "message": f"{flavor}{'·加大' if is_large else ''}{'·重量' if is_heavy else ''}{'·加蛋' if extra_egg else ''} = {total}元",
        }

    def quote_riceball_customization_price(
        self,
        flavor: str,
        add_ingredients: Optional[List[str]] = None,
        remove_ingredients: Optional[List[str]] = None,
        only_ingredients: Optional[List[str]] = None,
        only_mode: bool = False,
    ) -> Dict[str, Any]:
        add_ingredients = _dedupe_keep_order(add_ingredients or [])
        remove_ingredients = _dedupe_keep_order(remove_ingredients or [])
        only_ingredients = _dedupe_keep_order(only_ingredients or [])

        default_recipe = self.get_riceball_recipe(flavor)
        default_ings = default_recipe.get("ingredients", []) if default_recipe.get("available") else []

        normalized_add: List[str] = []
        unknown_add: List[str] = []
        addon_total = 0

        for raw in add_ingredients:
            key = INGREDIENT_SYNONYMS.get(raw, raw)
            normalized_add.append(key)
            if key in self.ADDON_PRICE_TABLE:
                addon_total += int(self.ADDON_PRICE_TABLE[key])
            else:
                unknown_add.append(key)

        # 推估最後配料數量（僅用於判斷是否極端客製）
        if only_mode:
            final_ings = [INGREDIENT_SYNONYMS.get(x, x) for x in only_ingredients] if only_ingredients else []
        else:
            final_ings = [x for x in default_ings if x not in remove_ingredients]

        needs_price_confirm = False
        if only_mode:
            needs_price_confirm = True
        if len(final_ings) <= 1:
            needs_price_confirm = True

        # 人工定價（最低35，5元級距）
        if needs_price_confirm:
            min_price = 35
            step = 5
            suggested_prices = list(range(min_price, 105, step))  # 35~100
            return {
                "status": "needs_price_confirm",
                "flavor": flavor,
                "addon_total": None,
                "normalized_add": normalized_add,
                "unknown_add": unknown_add,
                "needs_store_confirm": True,
                "min_price": min_price,
                "step": step,
                "suggested_prices": suggested_prices,
                "message": "此為特殊客製，需人工確認價格（最低35元，5元級距）。",
            }

        return {
            "status": "success",
            "flavor": flavor,
            "addon_total": addon_total,
            "normalized_add": normalized_add,
            "unknown_add": unknown_add,
            "needs_store_confirm": len(unknown_add) > 0,
            "message": f"加料加價共 {addon_total} 元" + ("（含需店家確認項目）" if len(unknown_add) > 0 else ""),
        }

    def parse_riceball_utterance(self, text: str) -> Dict[str, Any]:
        original_text = text or ""
        t = (text or "").strip()

        quantity = 1
        # 支援：5個 / 25個 / 五個 / 二十五個
        m_num = re.search(r"(\d{1,2}|[零一二兩三四五六七八九十]{1,3})\s*(顆|個)", t)
        if m_num:
            token = m_num.group(1)
            if token.isdigit():
                quantity = int(token)
            else:
                v = _chinese_number_to_int(token)
                quantity = v if isinstance(v, int) and v > 0 else 1

        large = ("加大" in t) or ("大顆" in t)
        heavy = ("重量" in t)
        extra_egg = ("加蛋" in t)

        rice = None
        for kw, val in RICE_KEYWORDS.items():
            if kw in t:
                rice = val
                break

        flavor = None

        # alias：長字優先
        for alias in sorted(FLAVOR_ALIASES.keys(), key=len, reverse=True):
            if alias and alias in t:
                flavor = FLAVOR_ALIASES[alias]
                break

        # 若 alias 沒抓到，再嘗試直接命中 recipes key
        if flavor is None and self.recipes_data:
            keys = sorted(self.recipes_data.keys(), key=len, reverse=True)
            for k in keys:
                if k in t:
                    flavor = k
                    break

        # 注意：這裡刻意不做「飯糰/飯團 => 源味傳統」預設口味
        # 目的：讓「我要一個飯糰」先問口味，再問米種。

        add_ingredients: List[str] = []
        remove_ingredients: List[str] = []
        only_ingredients: List[str] = []

        only_mode = False
        needs_price_confirm = False

        # 特殊只要句型（預先定義）
        for pat in SPECIAL_ONLY_PATTERNS:
            if pat in t:
                only_mode = True
                needs_price_confirm = True
                if "蛋" in pat:
                    only_ingredients.append("蛋")
                break

        # 只要...（例如：只要肉鬆油條）
        if not only_mode:
            m_only = re.search(r"只要(.+)", t)
            if m_only:
                only_mode = True
                needs_price_confirm = True

                only_part = m_only.group(1)
                candidates = set()

                # recipes 配料
                for recipe in self.recipes_data.values():
                    for ing in recipe.get("ingredients", []):
                        candidates.add(ing)

                # synonyms：只收長度>=2，避免單字子字串污染（例：肉鬆 => 肉類）
                for syn in INGREDIENT_SYNONYMS.keys():
                    if len(syn) >= 2:
                        candidates.add(syn)

                for c in sorted(candidates, key=len, reverse=True):
                    if c and c in only_part:
                        only_ingredients.append(INGREDIENT_SYNONYMS.get(c, c))

                only_ingredients = _dedupe_keep_order(only_ingredients)

        # 加X / 再加X（加蛋由 extra_egg 控制，避免雙算）
        for syn in sorted(INGREDIENT_SYNONYMS.keys(), key=len, reverse=True):
            if syn in ("加蛋", "蛋"):
                continue
            if ("加" + syn) in t or ("再加" + syn) in t:
                add_ingredients.append(INGREDIENT_SYNONYMS.get(syn, syn))

        # 不要/去掉/拿掉X
        for syn in sorted(INGREDIENT_SYNONYMS.keys(), key=len, reverse=True):
            if ("不要" + syn) in t or ("去掉" + syn) in t or ("拿掉" + syn) in t:
                remove_ingredients.append(INGREDIENT_SYNONYMS.get(syn, syn))

        add_ingredients = _dedupe_keep_order(add_ingredients)
        remove_ingredients = _dedupe_keep_order(remove_ingredients)

        # DialogueManager will recompute missing_slots
        missing_slots = []
        if flavor is None:
            missing_slots.append("flavor")
        if rice is None:
            missing_slots.append("rice")

        return {
            "itemtype": "riceball",
            "flavor": flavor,
            "rice": rice,
            "large": bool(large),
            "heavy": bool(heavy),
            "extra_egg": bool(extra_egg),
            "quantity": int(quantity) if isinstance(quantity, int) and quantity > 0 else 1,
            "ingredients_mode": "only" if only_mode else "default",
            "ingredients_only": only_ingredients,
            "ingredients_add": add_ingredients,
            "ingredients_remove": remove_ingredients,
            "needs_price_confirm": needs_price_confirm,
            "raw_text": original_text,
            "missing_slots": missing_slots,
        }


menu_tool = MenuTool()

if __name__ == "__main__":
    print("MENU_TOOL_VERSION =", MENU_TOOL_VERSION)
    print("=== 測試：parse_riceball_utterance + quote_riceball_customization_price ===")

    tests = [
        "我要一個飯糰",
        "我要一個飯團",
        "我要一個飯糰醬燒里肌紫米",
        "我要一個飯糰 要蒜香的",
        "我要五個傳統飯糰",
        "我要25個傳統飯糰",
        "我要二十五個傳統飯糰",
        "源味傳統只要肉鬆",
        "只要飯跟蛋",
        "只要飯",
        "我要一個黑椒紫米",
        "我要一個泡菜白米",
    ]

    for s in tests:
        print("\n句子:", s)
        frame = menu_tool.parse_riceball_utterance(s)
        print("frame:", frame)

        if frame.get("flavor"):
            addon = menu_tool.quote_riceball_customization_price(
                flavor=frame["flavor"],
                add_ingredients=frame.get("ingredients_add", []),
                remove_ingredients=frame.get("ingredients_remove", []),
                only_ingredients=frame.get("ingredients_only", []),
                only_mode=(frame.get("ingredients_mode") == "only"),
            )
            print("addon_quote:", addon)


riceball_tool = MenuTool()