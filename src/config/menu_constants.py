"""菜單常數與分類建構工具"""
from typing import List

from src.tools.menu.menu_price_service import get_raw_menu

# 分類圖示對應表
CATEGORY_ICONS = {
    "飯糰": "🍙",
    "蛋餅": "🥞",
    "吐司": "🍞",
    "漢堡": "🍔",
    "饅頭": "🥟",
    "蔥抓餅": "🫓",
    "鐵板麵": "🍝",
    "點心": "🍟",
    "果醬吐司": "🍯",
    "飲品": "🥤",
    "套餐": "🍱",
}

# 分類固定排列順序
CATEGORY_ORDER = [
    "飯糰", "蛋餅", "吐司", "漢堡", "饅頭",
    "蔥抓餅", "鐵板麵", "點心", "果醬吐司", "飲品", "套餐",
]


def build_menu_categories() -> List[dict]:
    """
    從菜單讀取所有品項，按分類分組並加上 icon 和固定順序排列。
    格式：[{name, icon, items: [{name, price}]}]
    """
    menu_items = get_raw_menu()

    # 按分類分組
    categories_dict: dict = {}
    for item in menu_items:
        cat = item.get("category", "其他")
        if cat not in categories_dict:
            categories_dict[cat] = {
                "name": cat,
                "icon": CATEGORY_ICONS.get(cat, "📦"),
                "items": [],
            }
        categories_dict[cat]["items"].append({
            "name": item["name"],
            "price": item["price"],
        })

    # 按固定順序排列，未知分類附加在尾端
    categories = []
    for cat_name in CATEGORY_ORDER:
        if cat_name in categories_dict:
            categories.append(categories_dict[cat_name])
    # 補上不在預設順序中的分類（避免資料遺漏）
    for cat_name, cat_data in categories_dict.items():
        if cat_name not in CATEGORY_ORDER:
            categories.append(cat_data)

    return categories
