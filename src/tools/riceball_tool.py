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
from src.tools.text_utils import chinese_number_to_int, dedupe_keep_order

MENU_TOOL_VERSION = "2025-12-27-config-v6"

RECIPES_FILE = Path(__file__).parent / "menu" / "riceball_recipes.json"

# 從 config 載入別名與關鍵字
_cfg = load_json_config("aliases_riceball.json")
FLAVOR_ALIASES: Dict[str, str] = _cfg["flavor_aliases"]
RICE_KEYWORDS: Dict[str, str] = _cfg["rice_keywords"]
INGREDIENT_SYNONYMS: Dict[str, str] = _cfg["ingredient_synonyms"]
ORAL_RICEBALL_KEYWORDS: List[str] = _cfg["oral_riceball_keywords"]
SPECIAL_ONLY_PATTERNS: List[str] = _cfg["special_only_patterns"]

# 從 price_rules.json 載入飯糰價格規則
_price_cfg = load_json_config("price_rules.json")
SPECIAL_FLAVORS_ONLY_LARGE: set = set(_price_cfg["riceball"]["special_flavors_only_large"])
HEAVY_RICEBALL_PRICES: Dict[str, int] = _price_cfg["riceball"]["heavy_prices"]
_LARGE_SURCHARGE: int = _price_cfg["riceball"]["large_surcharge"]
_EXTRA_EGG_SURCHARGE: int = _price_cfg["riceball"]["extra_egg_surcharge"]

# 預排序別名（長字優先匹配）
_ALIASES_SORTED = tuple(sorted(FLAVOR_ALIASES.keys(), key=len, reverse=True))


def resolve_flavor(value: Optional[str]) -> Optional[str]:
    """別名 → 標準口味名；None 或無匹配原樣回傳"""
    if value is None:
        return None
    for alias in _ALIASES_SORTED:
        if alias == value or alias in value:
            return FLAVOR_ALIASES[alias]
    return value


def build_cart_item(
    flavor: Optional[str] = None,
    rice: Optional[str] = None,
    large: bool = False,
    extra_egg: bool = False,
    spicy: bool = False,
    quantity: int = 1,
    customization: Optional[str] = None,
) -> Dict[str, Any]:
    """驗證必填 + 解析別名 + 組裝購物車品項 dict（不含 item_id）"""
    missing: List[str] = []
    if not flavor:
        missing.append("flavor")
    if not rice:
        missing.append("rice")
    if missing:
        if "flavor" in missing and "rice" in missing:
            msg = "請問飯糰要什麼口味？紫米白米？"
        elif "flavor" in missing:
            msg = "請問飯糰要什麼口味？"
        else:
            msg = "飯糰要紫米白米？"
        return {"ok": False, "missing": missing, "message": msg}
    resolved = resolve_flavor(flavor)
    item: Dict[str, Any] = {
        "itemtype": "riceball",
        "flavor": resolved,
        "rice": rice,
        "large": bool(large),
        "extra_egg": bool(extra_egg),
        "spicy": bool(spicy),
        "quantity": max(1, quantity),
    }
    if customization:
        item["customization"] = customization
    return {"ok": True, "item": item, "display_name": f"{rice}{resolved}"}


# 向下相容別名（其他模組曾 import _chinese_number_to_int from riceball_tool）
_chinese_number_to_int = chinese_number_to_int
_dedupe_keep_order = dedupe_keep_order


class MenuTool:
    def __init__(self):
        self.menu_data = self._load_menu()
        self.recipes_data = self._load_recipes()

        self.ADDON_PRICE_TABLE: Dict[str, int] = _price_cfg["riceball"]["addon_prices"]

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
            "ok": bool(recipe),
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
        quantity: int = 1,
    ) -> Dict[str, Any]:
        items = self.menu_data.get("items", [])
        base_item = None

        for item in items:
            if item.get("category") == "飯糰" and flavor in item.get("name", ""):
                base_item = item
                break

        if not base_item:
            return {"ok": False, "message": f"找不到 '{flavor}'", "needs_confirm": True}

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
                    "ok": False,
                    "flavor": flavor,
                    "total_price": None,
                    "needs_confirm": True,
                    "message": f"{flavor}重量版需店家確認價格",
                }
            total = int(heavy_price)
        else:
            if is_large:
                total += _LARGE_SURCHARGE

        if extra_egg:
            total += _EXTRA_EGG_SURCHARGE

        qty = max(1, int(quantity))
        total_price = total * qty

        return {
            "ok": True,
            "flavor": flavor,
            "base_price": base_price,
            "large": is_large,
            "heavy": is_heavy,
            "extra_egg": bool(extra_egg),
            "quantity": qty,
            "single_price": total,
            "total_price": total_price,
            "needs_confirm": False,
            "message": f"{flavor}{'·加大' if is_large else ''}{'·重量' if is_heavy else ''}{'·加蛋' if extra_egg else ''} = {total_price}元",
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
        default_ings = (
            default_recipe.get("ingredients", []) if default_recipe.get("available") else []
        )

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
            final_ings = (
                [INGREDIENT_SYNONYMS.get(x, x) for x in only_ingredients]
                if only_ingredients
                else []
            )
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
                "ok": False,
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
            "ok": True,
            "flavor": flavor,
            "addon_total": addon_total,
            "normalized_add": normalized_add,
            "unknown_add": unknown_add,
            "needs_store_confirm": len(unknown_add) > 0,
            "message": f"加料加價共 {addon_total} 元"
            + ("（含需店家確認項目）" if len(unknown_add) > 0 else ""),
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
        heavy = "重量" in t
        extra_egg = "加蛋" in t

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


riceball_tool = menu_tool
