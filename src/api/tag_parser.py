# src/api/tag_parser.py
"""Text Tag 正則解析 + 購物車品項查找 + 取消意圖偵測"""

import re
from typing import Optional

# Text Tag 正則
REMOVE_RE = re.compile(r"\[REMOVE:(.+?)\]")
ADD_RE = re.compile(r"\[ADD:([^\]]+)\]")
SET_QTY_RE = re.compile(r"\[SET_QTY:([^\]]+)\]")
QUERY_RE = re.compile(r"\[QUERY(?::([^\]]*))?\]")

# 所有 tag 的 registry — 新增 tag 時在此登記，strip_all_tags 的 consumer 自動涵蓋
_ALL_TAG_RES = (ADD_RE, QUERY_RE, REMOVE_RE, SET_QTY_RE)


def strip_all_tags(text: str) -> str:
    """剝除文字中所有 text tag（含 [CHECKOUT]），供 TTS / 前端顯示前清理"""
    from src.dm.tool_priming import CHECKOUT_TAG

    for tag_re in _ALL_TAG_RES:
        text = tag_re.sub("", text)
    return text.replace(CHECKOUT_TAG, "")


# last_failed_attempt 中要保留的「客人實際提供的選項」鍵
PROVIDED_KEYS = ("rice", "size", "temp", "flavor", "noodle", "customization", "spicy", "extra_egg")

# 取消詞刻意收斂：只認終結性取消詞，不認單獨「不要」，
# 避免「飯糰不要辣」「不要香菜」這類加料偏好被誤判成取消品項。
_CANCEL_TRIGGERS = ("不要了", "不用了", "取消", "去掉", "拿掉", "刪掉", "移除", "不需要")
_CANCEL_ALL_KEYWORDS = ("全部", "都不要", "通通", "全不要", "都取消", "整單")


def find_cart_item_id(cart: list, keyword: str) -> Optional[str]:
    """正規化分隔符後用子字串比對找到購物車品項的 item_id"""
    from src.dm import cart_manager

    norm = keyword.replace("·", "").replace(" ", "")
    for item in cart:
        display = cart_manager.format_item(item).replace("·", "").replace(" ", "")
        if norm in display:
            return item.get("item_id")
    return None


def item_mentioned_in_text(item: dict, text: str) -> bool:
    """購物車品項是否在這句話被點名（顯示名 + 尾字類別名詞比對）。"""
    from src.dm import cart_manager

    display = cart_manager.format_item(item)
    core = display.split("(")[0].strip()
    if not core:
        return False
    if core in text:
        return True
    for piece in re.split(r"[·\s]+", core):
        if len(piece) >= 2 and piece in text:
            return True
    for n in (3, 2):
        if len(core) >= n and core[-n:] in text:
            return True
    return False


def parse_set_qty_tag(content: str) -> tuple[str, int]:
    """解析 [SET_QTY:品項|qty=N] tag 內容 → (品項名, 數量)"""
    parts = content.split("|")
    item_name = parts[0].strip()
    qty = 1
    if len(parts) > 1 and parts[1].strip().startswith("qty="):
        try:
            qty = int(parts[1].strip().split("=", 1)[1])
        except ValueError:
            pass
    return item_name, qty


def resolve_cancel_intent(text: str, cart: list) -> tuple[bool, list]:
    """偵測『取消品項』意圖並對應到 item_id。

    回傳 (是否整單取消, 要移除的 item_id 清單)；無明確取消意圖回 (False, [])。
    """
    if not cart or not any(kw in text for kw in _CANCEL_TRIGGERS):
        return False, []
    if any(kw in text for kw in _CANCEL_ALL_KEYWORDS):
        return True, []
    matched = [
        item["item_id"]
        for item in cart
        if item_mentioned_in_text(item, text) and item.get("item_id")
    ]
    return False, matched
