"""
Tool Call Pre-Execution Validator

在 benchmark tool loop 執行前，驗證 add_to_cart 的參數值是否合法。
合法值從 tool_registry 的別名表和菜單資料動態提取，不 hardcode。

設計原則：
- 只在 benchmark 層使用，不改動 production code
- 支援模糊匹配（子字串相似度），讓模型有機會自修正
- 回傳格式對齊 add_to_cart 的錯誤回傳：{"ok": false, "message": "..."}
"""

from __future__ import annotations

import difflib
from typing import Any, Optional


def _get_riceball_valid_flavors() -> list[str]:
    """
    飯糰合法口味清單：
    - FLAVOR_ALIASES 的所有 value（標準別名名稱，不含「飯糰」後綴）
    - 菜單中「飯糰」分類的名稱去掉「飯糰」後綴
    兩者合集，用於建議時顯示。
    """
    from src.tools.riceball_tool import FLAVOR_ALIASES
    from src.tools.menu import menu_price_service

    flavors: set[str] = set(FLAVOR_ALIASES.values())
    menu = menu_price_service.get_raw_menu()
    for item in menu:
        if item.get("category") == "飯糰":
            name: str = item.get("name", "")
            # 菜單名稱格式：「鮪魚飯糰」→ 去掉「飯糰」後綴
            if name.endswith("飯糰"):
                flavors.add(name[:-2])
            flavors.add(name)  # 原始全名也加入（供模型參考）
    return sorted(flavors)


def _get_drink_valid_flavors() -> list[str]:
    """從飲料別名表提取所有合法的標準飲料名（去重）"""
    from src.tools.drink_tool import DRINK_ALIASES

    return sorted(set(DRINK_ALIASES.values()))


def _get_egg_pancake_valid_flavors() -> list[str]:
    """從蛋餅別名表提取所有合法的標準口味（去重）"""
    from src.tools.egg_pancake_tool import EggPancakeTool

    return sorted(set(EggPancakeTool.FLAVOR_ALIASES.values()))


def _get_snack_valid_flavors() -> list[str]:
    """從點心別名表提取所有合法的標準品名（去重）"""
    from src.tools.snack_tool import SNACK_ALIASES

    return sorted(set(SNACK_ALIASES.values()))


def _get_carrier_valid_flavors() -> list[str]:
    """從菜單提取吐司、漢堡、饅頭的合法口味（去掉後綴載體名）"""
    from src.tools.menu import menu_price_service

    menu = menu_price_service.get_raw_menu()
    flavors: set[str] = set()
    for item in menu:
        cat = item.get("category", "")
        name = item.get("name", "")
        if cat in ("吐司", "漢堡", "饅頭"):
            # 原始名稱也是合法的（如「豬肉蛋吐司」整串）
            flavors.add(name)
            # 去掉「吐司」「漢堡」「饅頭」等後綴，留口味部分
            for suffix in ("蛋吐司", "吐司", "蛋漢堡", "堡", "漢堡", "蛋饅頭", "饅頭"):
                if name.endswith(suffix):
                    flavors.add(name[: -len(suffix)])
                    break
    return sorted(flavors)


def _get_carrier_valid_types() -> list[str]:
    """carrier 欄位的合法值（吐司/漢堡/饅頭）"""
    return ["吐司", "漢堡", "饅頭"]


def _get_jam_toast_valid_flavors() -> list[str]:
    """從菜單提取果醬吐司的合法口味"""
    from src.tools.menu import menu_price_service

    menu = menu_price_service.get_raw_menu()
    flavors: set[str] = set()
    for item in menu:
        if item.get("category") == "果醬吐司":
            name: str = item.get("name", "")
            # 格式：果醬吐司(草莓/薄片) → 提取「草莓」
            if "(" in name and "/" in name:
                inner = name.split("(")[1].split("/")[0]
                flavors.add(inner)
    return sorted(flavors)


def _fuzzy_suggest(value: str, valid_list: list[str], n: int = 3) -> list[str]:
    """用 difflib 找最接近的候選，輔助模型自修正"""
    matches = difflib.get_close_matches(value, valid_list, n=n, cutoff=0.4)
    if not matches:
        # 降級：子字串包含匹配
        matches = [v for v in valid_list if value in v or v in value][:n]
    return matches


def _is_riceball_flavor_valid(flavor: str) -> bool:
    """
    判斷飯糰口味是否合法：
    1. 能通過 FLAVOR_ALIASES 別名解析（alias key 包含或等於 flavor）
    2. flavor 本身就是別名 value（標準名稱）
    3. 菜單「飯糰」分類中存在以 flavor 開頭或包含 flavor 的品項
    """
    from src.tools.riceball_tool import FLAVOR_ALIASES
    from src.tools.menu import menu_price_service

    # 條件 1：能被別名解析
    for alias in sorted(FLAVOR_ALIASES.keys(), key=len, reverse=True):
        if alias == flavor or alias in flavor:
            return True

    # 條件 2：本身是別名 value（別名 value 不帶「飯糰」後綴）
    if flavor in set(FLAVOR_ALIASES.values()):
        return True

    # 條件 3：菜單中存在符合的品項
    menu = menu_price_service.get_raw_menu()
    for item in menu:
        if item.get("category") == "飯糰":
            item_name: str = item.get("name", "")
            if flavor in item_name or item_name.startswith(flavor):
                return True

    return False


def _validate_riceball(args: dict[str, Any]) -> Optional[dict[str, Any]]:
    """驗證飯糰參數"""
    flavor = args.get("flavor")
    rice = args.get("rice")

    errors: list[str] = []

    if flavor is not None:
        if not _is_riceball_flavor_valid(flavor):
            valid_flavors = _get_riceball_valid_flavors()
            suggestions = _fuzzy_suggest(flavor, valid_flavors)
            suggestion_str = "、".join(suggestions) if suggestions else "、".join(valid_flavors[:5])
            errors.append(
                f"飯糰口味 '{flavor}' 不在菜單中。"
                f"可選口味（部分）：{suggestion_str}"
            )

    if rice is not None:
        valid_rice = ["白米", "紫米", "混米"]
        if rice not in valid_rice:
            errors.append(f"米種 '{rice}' 不合法，可選：{'、'.join(valid_rice)}")

    return _build_error(errors)


def _is_drink_flavor_valid(flavor: str) -> bool:
    """判斷飲料品項是否合法（別名解析 + 菜單存在）"""
    from src.tools.drink_tool import DRINK_ALIASES
    from src.tools.menu import menu_price_service

    # 能被別名解析
    for alias in sorted(DRINK_ALIASES.keys(), key=len, reverse=True):
        if alias == flavor or alias in flavor:
            return True

    # 本身是別名 value
    if flavor in set(DRINK_ALIASES.values()):
        return True

    # 菜單「飲品」分類中存在（菜單名稱格式：「有糖豆漿(中)」）
    menu = menu_price_service.get_raw_menu()
    for item in menu:
        if item.get("category") == "飲品":
            item_name: str = item.get("name", "")
            # 去掉杯型後綴再比對
            base_name = item_name.split("(")[0] if "(" in item_name else item_name
            if flavor == base_name or flavor in item_name:
                return True

    return False


def _validate_drink(args: dict[str, Any]) -> Optional[dict[str, Any]]:
    """驗證飲料參數"""
    flavor = args.get("flavor")
    size = args.get("size")
    temp = args.get("temp")

    errors: list[str] = []

    if flavor is not None:
        if not _is_drink_flavor_valid(flavor):
            valid_flavors = _get_drink_valid_flavors()
            suggestions = _fuzzy_suggest(flavor, valid_flavors)
            suggestion_str = "、".join(suggestions) if suggestions else "、".join(valid_flavors[:5])
            errors.append(
                f"飲料品項 '{flavor}' 不在菜單中。"
                f"可選飲料（部分）：{suggestion_str}"
            )

    if size is not None:
        valid_sizes = ["中杯", "大杯"]
        from src.tools.drink_tool import SIZE_MAP

        resolved_size = SIZE_MAP.get(size, size)
        if resolved_size not in valid_sizes:
            errors.append(f"飲料杯型 '{size}' 不合法，可選：{'、'.join(valid_sizes)}")

    if temp is not None:
        valid_temps = ["冰", "溫", "熱"]
        from src.tools.drink_tool import TEMP_MAP

        resolved_temp = TEMP_MAP.get(temp, temp)
        if resolved_temp not in valid_temps:
            errors.append(f"溫度 '{temp}' 不合法，可選：{'、'.join(valid_temps)}")

    return _build_error(errors)


def _validate_carrier(args: dict[str, Any]) -> Optional[dict[str, Any]]:
    """驗證載體（吐司/漢堡/饅頭）參數"""
    carrier = args.get("carrier")
    flavor = args.get("flavor")

    errors: list[str] = []

    if carrier is not None:
        valid_carriers = _get_carrier_valid_types()
        if carrier not in valid_carriers:
            suggestions = _fuzzy_suggest(carrier, valid_carriers)
            suggestion_str = "、".join(suggestions) if suggestions else "、".join(valid_carriers)
            errors.append(
                f"載體類型 '{carrier}' 不合法。"
                f"可選：{suggestion_str}（吐司、漢堡、饅頭其中之一）"
            )

    if flavor is not None and carrier is not None:
        # 驗證「carrier + flavor」的組合是否存在於菜單
        from src.tools.menu import menu_price_service

        menu = menu_price_service.get_raw_menu()
        # 找該 carrier 分類下的所有品項
        carrier_items = [
            item["name"] for item in menu if item.get("category") == carrier
        ]
        # 嘗試比對（flavor 可能是不含載體名的口味部分）
        matched = any(
            flavor in item_name or item_name.startswith(flavor)
            for item_name in carrier_items
        )
        if not matched and carrier_items:
            # 提取口味部分給模型參考
            flavor_parts: list[str] = []
            for item_name in carrier_items:
                for suffix in ("蛋吐司", "吐司", "蛋漢堡", "堡", "漢堡", "蛋饅頭", "饅頭"):
                    if item_name.endswith(suffix):
                        flavor_parts.append(item_name[: -len(suffix)])
                        break
                else:
                    flavor_parts.append(item_name)
            suggestions = _fuzzy_suggest(flavor, flavor_parts)
            suggestion_str = "、".join(suggestions) if suggestions else "、".join(flavor_parts[:5])
            errors.append(
                f"{carrier}的口味 '{flavor}' 不在菜單中。"
                f"可選口味（部分）：{suggestion_str}"
            )

    return _build_error(errors)


def _is_egg_pancake_flavor_valid(flavor: str) -> bool:
    """判斷蛋餅口味是否合法（別名解析 + 菜單存在）"""
    from src.tools.egg_pancake_tool import EggPancakeTool
    from src.tools.menu import menu_price_service

    for alias in sorted(EggPancakeTool.FLAVOR_ALIASES.keys(), key=len, reverse=True):
        if alias == flavor or alias in flavor:
            return True

    if flavor in set(EggPancakeTool.FLAVOR_ALIASES.values()):
        return True

    menu = menu_price_service.get_raw_menu()
    for item in menu:
        if item.get("category") == "蛋餅":
            if flavor == item.get("name") or flavor in item.get("name", ""):
                return True

    return False


def _validate_egg_pancake(args: dict[str, Any]) -> Optional[dict[str, Any]]:
    """驗證蛋餅參數"""
    flavor = args.get("flavor")
    if flavor is None:
        return None

    errors: list[str] = []

    if not _is_egg_pancake_flavor_valid(flavor):
        valid_flavors = _get_egg_pancake_valid_flavors()
        suggestions = _fuzzy_suggest(flavor, valid_flavors)
        suggestion_str = "、".join(suggestions) if suggestions else "、".join(valid_flavors[:5])
        errors.append(
            f"蛋餅口味 '{flavor}' 不在菜單中。"
            f"可選口味（部分）：{suggestion_str}"
        )

    return _build_error(errors)


def _validate_jam_toast(args: dict[str, Any]) -> Optional[dict[str, Any]]:
    """驗證果醬吐司參數"""
    flavor = args.get("flavor")
    size = args.get("size")

    errors: list[str] = []

    if flavor is not None:
        valid_flavors = _get_jam_toast_valid_flavors()
        if flavor not in valid_flavors:
            suggestions = _fuzzy_suggest(flavor, valid_flavors)
            suggestion_str = "、".join(suggestions) if suggestions else "、".join(valid_flavors)
            errors.append(
                f"果醬吐司口味 '{flavor}' 不在菜單中。"
                f"可選口味：{suggestion_str}"
            )

    if size is not None:
        valid_sizes = ["薄片", "厚片"]
        if size not in valid_sizes:
            errors.append(f"果醬吐司厚度 '{size}' 不合法，可選：{'、'.join(valid_sizes)}")

    return _build_error(errors)


def _is_snack_flavor_valid(flavor: str) -> bool:
    """判斷點心品項是否合法（別名解析 + 菜單存在）"""
    from src.tools.snack_tool import SNACK_ALIASES
    from src.tools.menu import menu_price_service

    for alias in sorted(SNACK_ALIASES.keys(), key=len, reverse=True):
        if alias == flavor or alias in flavor:
            return True

    if flavor in set(SNACK_ALIASES.values()):
        return True

    menu = menu_price_service.get_raw_menu()
    for item in menu:
        if item.get("category") == "點心":
            if flavor == item.get("name") or flavor in item.get("name", ""):
                return True

    return False


def _validate_snack(args: dict[str, Any]) -> Optional[dict[str, Any]]:
    """驗證點心參數"""
    flavor = args.get("flavor")
    if flavor is None:
        return None

    errors: list[str] = []

    if not _is_snack_flavor_valid(flavor):
        valid_flavors = _get_snack_valid_flavors()
        suggestions = _fuzzy_suggest(flavor, valid_flavors)
        suggestion_str = "、".join(suggestions) if suggestions else "、".join(valid_flavors[:5])
        errors.append(
            f"點心品項 '{flavor}' 不在菜單中。"
            f"可選點心（部分）：{suggestion_str}"
        )

    return _build_error(errors)


def _validate_combo(args: dict[str, Any]) -> Optional[dict[str, Any]]:
    """驗證套餐參數"""
    combo_name = args.get("combo_name")
    if combo_name is None:
        return None

    valid_combos = ["套餐一", "套餐二", "套餐三", "套餐四", "套餐五", "套餐六", "套餐七",
                    "套餐A", "套餐B", "套餐C", "套餐D", "套餐E", "兒童餐"]
    errors: list[str] = []

    if combo_name not in valid_combos:
        suggestions = _fuzzy_suggest(combo_name, valid_combos)
        suggestion_str = "、".join(suggestions) if suggestions else "、".join(valid_combos)
        errors.append(
            f"套餐名稱 '{combo_name}' 不存在。"
            f"可選套餐：{suggestion_str}"
        )

    return _build_error(errors)


def _build_error(errors: list[str]) -> Optional[dict[str, Any]]:
    """組合錯誤訊息，無錯誤回傳 None"""
    if not errors:
        return None
    message = "參數驗證失敗：" + "；".join(errors) + "。請修正後重新呼叫 add_to_cart。"
    return {"ok": False, "message": message}


# item_type → 驗證函數的路由表
_VALIDATORS = {
    "riceball": _validate_riceball,
    "drink": _validate_drink,
    "carrier": _validate_carrier,
    "egg_pancake": _validate_egg_pancake,
    "jam_toast": _validate_jam_toast,
    "snack": _validate_snack,
    "combo": _validate_combo,
}

# 合法的 item_type 清單
_VALID_ITEM_TYPES = list(_VALIDATORS.keys())


def validate_add_to_cart(arguments: dict[str, Any]) -> Optional[dict[str, Any]]:
    """
    驗證 add_to_cart 的參數值是否合法。

    Args:
        arguments: LLM 傳入的 add_to_cart 參數字典

    Returns:
        驗證失敗時回傳 {"ok": False, "message": "..."}，
        驗證通過時回傳 None（讓 adapter 繼續執行工具）
    """
    item_type = arguments.get("item_type")

    # 驗證 item_type 本身
    if item_type not in _VALID_ITEM_TYPES:
        suggestions = _fuzzy_suggest(str(item_type), _VALID_ITEM_TYPES) if item_type else []
        suggestion_str = "、".join(suggestions) if suggestions else "、".join(_VALID_ITEM_TYPES)
        return {
            "ok": False,
            "message": (
                f"item_type '{item_type}' 不合法。"
                f"可選：{suggestion_str}"
                f"。請修正後重新呼叫 add_to_cart。"
            ),
        }

    # 依 item_type 派發到對應驗證器
    validator = _VALIDATORS[item_type]
    return validator(arguments)
