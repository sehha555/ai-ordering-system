# -*- coding: utf-8 -*-
"""
共用文字工具函式 — 各工具間共用的數字、去重、數量解析邏輯
"""

import re
from typing import List, Optional

# 數量對應表（支援到 99：阿拉伯數字 + 中文數字）
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


def chinese_number_to_int(token: str) -> Optional[int]:
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


def dedupe_keep_order(xs: List[str]) -> List[str]:
    """去除重複元素，保留原始順序"""
    return list(dict.fromkeys(xs or []))


def parse_quantity(text: str, units: tuple = ("個", "顆", "份")) -> int:
    """
    從文字解析數量。

    優先匹配阿拉伯數字 + 計量詞，其次匹配中文數字 + 計量詞。
    若無匹配則回傳 1。

    Args:
        text: 輸入文字
        units: 可接受的計量詞 tuple，例如 ("個", "顆") 或 ("杯",)

    Returns:
        解析出的數量，最小為 1
    """
    units_pattern = "|".join(re.escape(u) for u in units)

    # 阿拉伯數字 + 計量詞
    m = re.search(rf"(\d{{1,2}})\s*(?:{units_pattern})", text)
    if m:
        q = int(m.group(1))
        return q if q > 0 else 1

    # 中文數字 + 計量詞
    m2 = re.search(rf"([零一二兩三四五六七八九十]{{1,3}})\s*(?:{units_pattern})", text)
    if m2:
        v = chinese_number_to_int(m2.group(1))
        return v if isinstance(v, int) and v > 0 else 1

    return 1
