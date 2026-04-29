"""
菜單狀態管理服務

負責管理品項售完狀態、分類控制、連動規則、套餐狀態和營業時間。
狀態持久化於 menu_state.json，使用 file lock 避免 race condition。
"""

import json
import os
import threading
from datetime import datetime
from typing import Optional

# 狀態快取，避免每次都讀 JSON
_state_cache: Optional[dict] = None
# 用於保護 JSON 讀寫的執行緒鎖
_file_lock = threading.Lock()

_STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "menu_state.json")

# ── 所有分類控制 key 的預設初始值 ──────────────────────────────────────────
_DEFAULT_CATEGORIES = {
    "carrier_toast": False,
    "carrier_burger": False,
    "carrier_thick_toast": False,
    "rice_purple": False,
    "rice_white": False,
    "mantou_black_sugar": False,
    "mantou_white": False,
    "mantou_black_sugar_roll": False,
    "mantou_white_roll": False,
    "mantou_taro": False,
    "noodle_oil": False,
    "noodle_udon": False,
    "scallion_pancake": False,
}

# ── 吐司分類品項（carrier_toast 關掉後全部不可用）──────────────────────────
_TOAST_ITEMS = [
    "煎蛋吐司",
    "起司蛋吐司",
    "火腿蛋吐司",
    "豬肉蛋吐司",
    "培根蛋吐司",
    "薯餅蛋吐司",
    "鮪魚蛋吐司",
    "蜜汁燒肉蛋吐司",
    "醬燒肉片蛋吐司",
    "黑椒肉片蛋吐司",
    "原味咔啦雞蛋吐司",
    "無骨雞排蛋吐司",
    "醬燒肉片總匯吐司",
]

# ── 薄片果醬吐司（carrier_toast 關掉後連動）─────────────────────────────
_JAM_TOAST_THIN = [
    "果醬吐司(草莓/薄片)",
    "果醬吐司(花生/薄片)",
    "果醬吐司(蒜香/薄片)",
    "果醬吐司(奶酥/薄片)",
    "果醬吐司(巧克力/薄片)",
]

# ── 厚片果醬吐司（carrier_thick_toast 關掉後連動）──────────────────────
_JAM_TOAST_THICK = [
    "果醬吐司(草莓/厚片)",
    "果醬吐司(花生/厚片)",
    "果醬吐司(蒜香/厚片)",
    "果醬吐司(奶酥/厚片)",
    "果醬吐司(巧克力/厚片)",
]

# ── 漢堡分類品項（carrier_burger 關掉後全部不可用）──────────────────────
_BURGER_ITEMS = [
    "火腿蛋漢堡",
    "起司蛋漢堡",
    "豬肉蛋漢堡",
    "薯餅蛋漢堡",
    "培根蛋漢堡",
    "鮪魚蛋漢堡",
    "椒鹽雞絲蛋漢堡",
    "醬燒肉片蛋漢堡",
    "黑椒肉片蛋漢堡",
    "原味咔啦雞蛋漢堡",
    "無骨雞排蛋堡",
]

# ── 饅頭種類 → 分類 key 對應品項名稱 ──────────────────────────────────
_MANTOU_CATEGORY_TO_ITEM = {
    "mantou_black_sugar": "黑糖饅頭",
    "mantou_white": "白饅頭",
    "mantou_black_sugar_roll": "黑糖花捲",
    "mantou_white_roll": "白花捲",
    "mantou_taro": "芋頭饅頭",
}

# ── 鐵板麵 SKU（4 口味 × 2 麵體）──────────────────────────────────────
_IRON_NOODLE_OIL_SKUS = [
    "黑椒鐵板麵(油麵)+蛋",
    "蘑菇鐵板麵(油麵)+蛋",
    "義大利肉醬鐵板麵(油麵)+蛋",
    "咖哩鐵板麵(油麵)+蛋",
]
_IRON_NOODLE_UDON_SKUS = [
    "黑椒鐵板麵(烏龍)+蛋",
    "蘑菇鐵板麵(烏龍)+蛋",
    "義大利肉醬鐵板麵(烏龍)+蛋",
    "咖哩鐵板麵(烏龍)+蛋",
]


# ── 內部工具函式 ─────────────────────────────────────────────────────────


def _load_state() -> dict:
    """讀取 menu_state.json，若檔案不存在則回傳預設狀態。"""
    global _state_cache
    if _state_cache is not None:
        return _state_cache

    if not os.path.exists(_STATE_FILE):
        _state_cache = _default_state()
        return _state_cache

    with open(_STATE_FILE, "r", encoding="utf-8") as f:
        _state_cache = json.load(f)
    return _state_cache


def _save_state(state: dict) -> None:
    """將狀態寫回 JSON 檔案，同時更新快取。"""
    global _state_cache
    with open(_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    _state_cache = state


def _default_state() -> dict:
    """回傳初始狀態結構。"""
    return {
        "sold_out_items": [],
        "sold_out_categories": dict(_DEFAULT_CATEGORIES),
        "business_hours": {"open": "06:00", "close": "14:00"},
        "is_open_override": None,
    }


# ── 公開 API ─────────────────────────────────────────────────────────────


def get_state() -> dict:
    """取得完整狀態（sold_out_items、sold_out_categories、business_hours、is_open_override）。"""
    with _file_lock:
        return _load_state()


def get_sold_out_items() -> list[str]:
    """取得品項級售完清單（不含連動推算）。"""
    with _file_lock:
        return list(_load_state().get("sold_out_items", []))


def get_sold_out_categories() -> dict:
    """取得分類級售完狀態字典。"""
    with _file_lock:
        return dict(_load_state().get("sold_out_categories", {}))


def set_item_sold_out(name: str, sold_out: bool) -> None:
    """設定單品售完狀態。sold_out=True 加入清單，False 從清單移除。"""
    with _file_lock:
        state = _load_state()
        items: list = state.setdefault("sold_out_items", [])
        if sold_out:
            if name not in items:
                items.append(name)
        else:
            if name in items:
                items.remove(name)
        _save_state(state)


def set_category_sold_out(key: str, sold_out: bool) -> None:
    """設定分類售完狀態。key 必須是合法的分類控制 key。"""
    if key not in _DEFAULT_CATEGORIES:
        raise KeyError(f"不合法的分類控制 key：{key}")
    with _file_lock:
        state = _load_state()
        state.setdefault("sold_out_categories", {})[key] = sold_out
        _save_state(state)


def reset_all_sold_out() -> None:
    """一鍵恢復全部售完（品項清單清空，所有分類設為 False）。"""
    with _file_lock:
        state = _load_state()
        state["sold_out_items"] = []
        state["sold_out_categories"] = dict(_DEFAULT_CATEGORIES)
        _save_state(state)


def get_effective_sold_out() -> list[str]:
    """
    套用所有連動規則，回傳最終售完品項清單。

    連動規則：
      規則1：載體關 → 對應載體所有品項 + 相關果醬吐司連動
      規則2：米種連動 → 紫米或白米關 → 混米自動關
      規則3：饅頭種類 → 各自獨立，分類 key 對應單一品項
      規則4：鐵板麵麵種 → 油麵關=4 個油麵 SKU 關；烏龍關=4 個烏龍 SKU 關
      規則5：蔥抓餅關 → 蔥抓餅(原味) + 蔥抓餅(加蛋) 都關
    """
    with _file_lock:
        state = _load_state()

    sold_items: set[str] = set(state.get("sold_out_items", []))
    cats: dict = state.get("sold_out_categories", {})

    # 規則1：吐司載體關
    if cats.get("carrier_toast"):
        sold_items.update(_TOAST_ITEMS)
        sold_items.update(_JAM_TOAST_THIN)

    # 規則1：厚片載體關
    if cats.get("carrier_thick_toast"):
        sold_items.update(_JAM_TOAST_THICK)

    # 規則1：漢堡載體關
    if cats.get("carrier_burger"):
        sold_items.update(_BURGER_ITEMS)

    # 規則2：米種連動（米種是飯糰的點餐選項，不是獨立品項）
    # get_rice_options_status() 負責回傳選項狀態供 system prompt 使用
    # 此處不加假品項名（menu 中不存在「紫米飯糰」等品項）

    # 規則3：饅頭各自獨立
    for cat_key, item_name in _MANTOU_CATEGORY_TO_ITEM.items():
        if cats.get(cat_key):
            sold_items.add(item_name)

    # 規則4：鐵板麵麵種（4 口味 × 2 麵體 = 8 SKU）
    if cats.get("noodle_oil", False):
        sold_items.update(_IRON_NOODLE_OIL_SKUS)
    if cats.get("noodle_udon", False):
        sold_items.update(_IRON_NOODLE_UDON_SKUS)

    # 規則5：蔥抓餅關
    if cats.get("scallion_pancake"):
        sold_items.add("蔥抓餅(原味)")
        sold_items.add("蔥抓餅(加蛋)")

    return sorted(sold_items)


def get_effective_combo_status() -> dict:
    """
    計算套餐可用狀態。

    回傳 dict，key 為套餐簡稱（如 "套餐一"），value 為：
      {"available": bool, "reason": str | None}
    reason 只在 available=False 時有值，說明關閉原因。
    """
    with _file_lock:
        state = _load_state()

    sold_items: set[str] = set(state.get("sold_out_items", []))
    cats: dict = state.get("sold_out_categories", {})

    # 預先計算常用條件
    toast_off = cats.get("carrier_toast", False)
    burger_off = cats.get("carrier_burger", False)
    thick_toast_off = cats.get("carrier_thick_toast", False)
    rice_purple_off = cats.get("rice_purple", False)
    rice_white_off = cats.get("rice_white", False)
    noodle_udon_off = cats.get("noodle_udon", False)
    noodle_oil_off = cats.get("noodle_oil", False)
    all_noodles_off = noodle_udon_off and noodle_oil_off

    # 判斷 5 種饅頭是否全部售完（分類 key + 品項 sold_out 兩者都算）
    def _mantou_item_sold_out(cat_key: str) -> bool:
        item = _MANTOU_CATEGORY_TO_ITEM[cat_key]
        return cats.get(cat_key, False) or item in sold_items

    all_mantou_off = all(_mantou_item_sold_out(k) for k in _MANTOU_CATEGORY_TO_ITEM)

    # 無骨雞排是否售完
    chicken_off = "無骨雞排" in sold_items

    def _make(available: bool, reason: Optional[str] = None) -> dict:
        return {"available": available, "reason": reason}

    result: dict[str, dict] = {}

    # 套餐一：醬燒肉片蛋餅售完 → 關
    item_1 = "醬燒肉片蛋餅" in sold_items
    result["套餐一"] = _make(not item_1, "醬燒肉片蛋餅售完" if item_1 else None)

    # 套餐二：紫米+白米都關 → 關
    rice_both_off = rice_purple_off and rice_white_off
    result["套餐二"] = _make(not rice_both_off, "紫米與白米均售完" if rice_both_off else None)

    # 套餐三：高麗菜蛋餅售完 → 關
    item_3 = "高麗菜蛋餅" in sold_items
    result["套餐三"] = _make(not item_3, "高麗菜蛋餅售完" if item_3 else None)

    # 套餐四：港式蘿蔔糕售完 → 關
    item_4 = "港式蘿蔔糕" in sold_items
    result["套餐四"] = _make(not item_4, "港式蘿蔔糕售完" if item_4 else None)

    # 套餐五：5 種饅頭都關 → 關
    result["套餐五"] = _make(not all_mantou_off, "所有饅頭種類均售完" if all_mantou_off else None)

    # 套餐六：油麵+烏龍都關 → 關
    result["套餐六"] = _make(not all_noodles_off, "油麵與烏龍麵均售完" if all_noodles_off else None)

    # 套餐七：油麵+烏龍都關 OR 無骨雞排售完 → 關
    combo7_off = all_noodles_off or chicken_off
    if combo7_off:
        reason7 = []
        if all_noodles_off:
            reason7.append("油麵與烏龍麵均售完")
        if chicken_off:
            reason7.append("無骨雞排售完")
        result["套餐七"] = _make(False, "、".join(reason7))
    else:
        result["套餐七"] = _make(True)

    # 套餐A：吐司關 → 關
    result["套餐A"] = _make(not toast_off, "吐司售完" if toast_off else None)

    # 套餐B：厚片關 → 關
    result["套餐B"] = _make(not thick_toast_off, "厚片吐司售完" if thick_toast_off else None)

    # 套餐C：油麵+烏龍都關 OR 兩個義大利肉醬鐵板麵 SKU 都售完 → 關
    italian_off = (
        "義大利肉醬鐵板麵(油麵)+蛋" in sold_items and "義大利肉醬鐵板麵(烏龍)+蛋" in sold_items
    )
    comboC_off = all_noodles_off or italian_off
    if comboC_off:
        reasonC = "義大利肉醬麵售完" if italian_off else "油麵與烏龍麵均售完"
        result["套餐C"] = _make(False, reasonC)
    else:
        result["套餐C"] = _make(True)

    # 套餐D：吐司關 → 關
    result["套餐D"] = _make(not toast_off, "吐司售完" if toast_off else None)

    # 套餐E：漢堡關 OR 無骨雞排售完 → 關
    comboE_off = burger_off or chicken_off
    if comboE_off:
        reasonE = []
        if burger_off:
            reasonE.append("漢堡售完")
        if chicken_off:
            reasonE.append("無骨雞排售完")
        result["套餐E"] = _make(False, "、".join(reasonE))
    else:
        result["套餐E"] = _make(True)

    # 兒童餐：吐司關 → 關
    result["兒童餐"] = _make(not toast_off, "吐司售完" if toast_off else None)

    return result


def get_rice_options_status() -> dict:
    """
    回傳飯糰米種選項的可用狀態。

    米種是飯糰的點餐選項，不是獨立品項，因此不進 effective_sold_out。
    此函式供 system_prompts.py 使用，以「選項限制」方式告知 LLM。

    回傳：
      {
        "purple": bool,  # True = 紫米可用，False = 紫米不可選
        "white":  bool,  # True = 白米可用，False = 白米不可選
        "mixed":  bool,  # True = 混米可用（紫米 AND 白米 都有時才 True）
      }
    """
    with _file_lock:
        state = _load_state()

    cats: dict = state.get("sold_out_categories", {})
    purple_off = cats.get("rice_purple", False)
    white_off = cats.get("rice_white", False)

    purple_ok = not purple_off
    white_ok = not white_off
    # 混米需要紫米和白米都有，任一缺貨就無法提供
    mixed_ok = purple_ok and white_ok

    return {
        "purple": purple_ok,
        "white": white_ok,
        "mixed": mixed_ok,
    }


# ── 營業時間 ─────────────────────────────────────────────────────────────


def get_business_hours() -> dict:
    """取得營業時間設定，回傳 {"open": "HH:MM", "close": "HH:MM"}。"""
    with _file_lock:
        return dict(_load_state().get("business_hours", {"open": "06:00", "close": "14:00"}))


def set_business_hours(open_time: str, close_time: str) -> None:
    """
    設定營業時間。
    open_time / close_time 格式：HH:MM（如 "06:00"）。
    """
    with _file_lock:
        state = _load_state()
        state["business_hours"] = {"open": open_time, "close": close_time}
        _save_state(state)


def is_currently_open() -> bool:
    """
    判斷目前是否營業。

    優先看 is_open_override：
      True  → 強制營業
      False → 強制休息
      None  → 依照 business_hours 判斷目前時間
    """
    with _file_lock:
        state = _load_state()

    override = state.get("is_open_override")
    if override is True:
        return True
    if override is False:
        return False

    # 自動模式：比對當前時間
    hours = state.get("business_hours", {"open": "06:00", "close": "14:00"})
    now = datetime.now().strftime("%H:%M")
    return hours["open"] <= now < hours["close"]


def set_open_override(override: Optional[bool]) -> None:
    """
    設定營業狀態 override。
      True  → 強制開
      False → 強制關
      None  → 回到自動（依營業時間判斷）
    """
    with _file_lock:
        state = _load_state()
        state["is_open_override"] = override
        _save_state(state)


def clear_cache() -> None:
    """清除模組級快取，測試用。"""
    global _state_cache
    _state_cache = None
