"""
Unified Tool Call Pre-Execution Validator

為 add_item tool 建立的驗證器。
add_item 使用單一 name 參數取代各 tool 的 flavor/carrier/combo_name 等欄位。

設計原則：
- 只在 benchmark 層使用，不改動 production code
- 從菜單和別名表動態建立合法品項索引
- 支援子字串匹配 + fuzzy suggest，讓模型有機會自修正
- 回傳格式對齊 add_item 的錯誤回傳：{"ok": false, "message": "..."}
"""

from __future__ import annotations

import difflib
from typing import Any, Optional


def _get_all_valid_names() -> list[str]:
    """取得所有合法品項名稱（含別名），用於 fuzzy suggest"""
    names: set[str] = set()

    # 菜單品項名稱
    try:
        from src.tools.menu import menu_price_service

        menu = menu_price_service.get_raw_menu()
        for item in menu:
            n = item.get("name", "")
            if n:
                names.add(n)
    except Exception:
        pass

    # 蛋餅別名
    try:
        from src.tools.egg_pancake_tool import EggPancakeTool

        names.update(EggPancakeTool.FLAVOR_ALIASES.keys())
        names.update(EggPancakeTool.FLAVOR_ALIASES.values())
    except Exception:
        pass

    # 飲料別名
    try:
        from src.tools.drink_tool import DRINK_ALIASES

        names.update(DRINK_ALIASES.keys())
        names.update(DRINK_ALIASES.values())
    except Exception:
        pass

    # 飯糰別名
    try:
        from src.tools.riceball_tool import FLAVOR_ALIASES

        names.update(FLAVOR_ALIASES.keys())
        names.update(FLAVOR_ALIASES.values())
    except Exception:
        pass

    # 點心別名
    try:
        from src.tools.snack_tool import SNACK_ALIASES

        names.update(SNACK_ALIASES.keys())
        names.update(SNACK_ALIASES.values())
    except Exception:
        pass

    return sorted(names)


def _fuzzy_suggest(value: str, valid_list: list[str], n: int = 3) -> list[str]:
    """用 difflib 找最接近的候選，輔助模型自修正"""
    matches = difflib.get_close_matches(value, valid_list, n=n, cutoff=0.4)
    if not matches:
        # 降級：子字串包含匹配
        matches = [v for v in valid_list if value in v or v in value][:n]
    return matches


def _is_name_valid(name: str) -> bool:
    """
    判斷 add_item 的 name 是否合法：
    1. 菜單中存在完全符合的品項名稱（含子字串）
    2. 能通過各工具的別名表解析
    """
    # 嘗試菜單直接比對（子字串）
    try:
        from src.tools.menu import menu_price_service

        menu = menu_price_service.get_raw_menu()
        for item in menu:
            item_name: str = item.get("name", "")
            if name in item_name or item_name in name:
                return True
    except Exception:
        pass

    # 蛋餅別名解析
    try:
        from src.tools.egg_pancake_tool import EggPancakeTool

        for alias in sorted(EggPancakeTool.FLAVOR_ALIASES.keys(), key=len, reverse=True):
            if alias == name or alias in name:
                return True
        if name in set(EggPancakeTool.FLAVOR_ALIASES.values()):
            return True
    except Exception:
        pass

    # 飲料別名解析
    try:
        from src.tools.drink_tool import DRINK_ALIASES

        for alias in sorted(DRINK_ALIASES.keys(), key=len, reverse=True):
            if alias == name or alias in name:
                return True
        if name in set(DRINK_ALIASES.values()):
            return True
    except Exception:
        pass

    # 飯糰別名解析
    try:
        from src.tools.riceball_tool import FLAVOR_ALIASES

        for alias in sorted(FLAVOR_ALIASES.keys(), key=len, reverse=True):
            if alias == name or alias in name:
                return True
        if name in set(FLAVOR_ALIASES.values()):
            return True
    except Exception:
        pass

    # 點心別名解析
    try:
        from src.tools.snack_tool import SNACK_ALIASES

        for alias in sorted(SNACK_ALIASES.keys(), key=len, reverse=True):
            if alias == name or alias in name:
                return True
        if name in set(SNACK_ALIASES.values()):
            return True
    except Exception:
        pass

    # 套餐名稱（固定清單）
    valid_combos = [
        "套餐一",
        "套餐二",
        "套餐三",
        "套餐四",
        "套餐五",
        "套餐六",
        "套餐七",
        "套餐A",
        "套餐B",
        "套餐C",
        "套餐D",
        "套餐E",
        "兒童餐",
    ]
    if name in valid_combos:
        return True

    return False


def _validate_drink_options(arguments: dict[str, Any]) -> list[str]:
    """驗證飲料的 size/temp 額外參數（若有傳入）"""
    errors: list[str] = []

    size = arguments.get("size")
    if size is not None:
        valid_sizes = ["中杯", "大杯"]
        try:
            from src.tools.drink_tool import SIZE_MAP

            resolved_size = SIZE_MAP.get(size, size)
        except Exception:
            resolved_size = size
        if resolved_size not in valid_sizes:
            errors.append(f"飲料杯型 '{size}' 不合法，可選：{'、'.join(valid_sizes)}")

    temp = arguments.get("temp")
    if temp is not None:
        valid_temps = ["冰", "溫", "熱"]
        try:
            from src.tools.drink_tool import TEMP_MAP

            resolved_temp = TEMP_MAP.get(temp, temp)
        except Exception:
            resolved_temp = temp
        if resolved_temp not in valid_temps:
            errors.append(f"溫度 '{temp}' 不合法，可選：{'、'.join(valid_temps)}")

    return errors


def _validate_riceball_options(arguments: dict[str, Any]) -> list[str]:
    """驗證飯糰的 rice 額外參數（若有傳入）
    饅頭品項允許用 rice 傳口味（如 rice='黑糖' = 黑糖饅頭），跳過米種驗證。
    """
    errors: list[str] = []

    rice = arguments.get("rice")
    if rice is not None:
        # 饅頭品項用 rice 欄位傳口味資訊（如 黑糖/白糖），不是米種，跳過驗證
        name = arguments.get("name", "")
        if "饅頭" in name:
            return errors
        valid_rice = ["白米", "紫米", "混米"]
        if rice not in valid_rice:
            errors.append(f"米種 '{rice}' 不合法，可選：{'、'.join(valid_rice)}")

    return errors


def validate_add_item(arguments: dict[str, Any]) -> Optional[dict[str, Any]]:
    """
    驗證 add_item 的 name 參數是否在菜單中。

    Args:
        arguments: LLM 傳入的 add_item 參數字典（必須含 name）

    Returns:
        驗證失敗時回傳 {"ok": False, "message": "..."}，
        驗證通過時回傳 None（讓 adapter 繼續執行工具）
    """
    name = arguments.get("name")

    # name 是必要參數
    if not name:
        return {
            "ok": False,
            "message": "缺少 name 參數。請指定要點的品項名稱（如「玉米蛋餅」、「紅茶」、「鮪魚飯糰」）。",
        }

    errors: list[str] = []

    # 驗證品項是否存在
    if not _is_name_valid(name):
        valid_names = _get_all_valid_names()
        suggestions = _fuzzy_suggest(name, valid_names)
        suggestion_str = "、".join(suggestions) if suggestions else "查詢菜單了解可用品項"
        errors.append(
            f"品項 '{name}' 不在菜單中。相近品項：{suggestion_str}。請修正後重新呼叫 add_item。"
        )
    else:
        # 品項合法，進一步驗證可選欄位
        errors.extend(_validate_drink_options(arguments))
        errors.extend(_validate_riceball_options(arguments))

    if not errors:
        return None

    message = "參數驗證失敗：" + "；".join(errors)
    return {"ok": False, "message": message}
