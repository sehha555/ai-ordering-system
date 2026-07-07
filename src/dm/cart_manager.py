import re
from collections import OrderedDict
from typing import Dict, Any, List, Optional

from src.tools.riceball_tool import menu_tool, INGREDIENT_SYNONYMS
from src.tools.text_utils import chinese_number_to_int, normalize_quantity
from src.tools.carrier_tool import carrier_tool
from src.tools.drink_tool import drink_tool
from src.tools.snack_tool import snack_tool
from src.tools.jam_toast_tool import jam_toast_tool
from src.tools.egg_pancake_tool import egg_pancake_tool
from src.tools.combo_tool import combo_tool


def _safe_quantity(item: Dict[str, Any]) -> int:
    """數量正規化：委派 text_utils.normalize_quantity"""
    return normalize_quantity(item.get("quantity", 1))


def format_item(frame: Dict[str, Any]) -> str:
    """格式化購物車品項為可讀字串（含客製後綴）

    customization 必須進顯示名：結帳確認句、廚房 items_display 都走這裡，
    不顯示等於客製資訊只存在資料裡、實際做餐會漏（如「蛋餅加辣」）
    """
    base = _format_item_base(frame)
    customization = frame.get("customization")
    if not customization:
        return base
    if base.endswith(")"):
        # 已有細節括號（如飲料的「(大杯, 冰)」）→ 併入同一組，避免雙括號
        return f"{base[:-1]}, {customization})"
    return f"{base}({customization})"


def _format_item_base(frame: Dict[str, Any]) -> str:
    rtype = frame.get("itemtype")
    if rtype == "drink":
        name = frame.get("drink", "飲料")
        details = [str(frame[k]) for k in ["size", "temp", "sugar"] if frame.get(k)]
        return f"{name}({', '.join(details)})" if details else name
    if rtype == "riceball":
        return f"{frame.get('rice', '')}{'·' if frame.get('rice') else ''}{frame.get('flavor', '飯糰')}"
    if rtype == "carrier":
        # menu_name 為菜單真實品名（source of truth），優先用；舊資料 fallback flavor+carrier
        return frame.get("menu_name") or f"{frame.get('flavor', '')}{frame.get('carrier', '餐點')}"
    if rtype == "egg_pancake":
        f = frame.get("flavor", "蛋餅")
        return f if f.endswith("蛋餅") else f"{f}蛋餅"
    if rtype == "snack":
        # 鐵板麵 menu_name 已含 (油麵)/(烏龍)，不再額外拼 noodle 後綴
        base = frame.get("snack", "點心")
        details = [
            v
            for v in [
                frame.get("egg_cook"),
                "不要胡椒" if frame.get("no_pepper") else None,
            ]
            if v
        ]
        return f"{base}({','.join(details)})" if details else base
    if rtype == "jam_toast":
        base = frame.get("jam_toast", "果醬吐司")
        details = [
            v
            for v in [
                "不烤" if frame.get("no_toast") else None,
                "切邊" if frame.get("cut_edge") else None,
            ]
            if v
        ]
        return f"{base}({','.join(details)})" if details else base
    if rtype == "combo":
        # 槽位必須進顯示：兩份套餐一冰一溫，廚房要看得出哪份是哪份
        base = frame.get("combo_name", "套餐")
        details = [
            v
            for v in [
                frame.get("sub_flavor"),
                frame.get("noodle"),
                frame.get("rice"),
                frame.get("drink_temp"),
            ]
            if v
        ]
        return f"{base}({', '.join(details)})" if details else base
    return "未知品項"


def _item_key(frame: Dict[str, Any]) -> str:
    """提取品項唯一身份（品項類型+格式化名稱），用於合併判斷"""
    rtype = frame.get("itemtype", "")
    name = format_item(frame)
    return f"{rtype}:{name}"


def get_price_info(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """根據品項類型取得價格資訊"""
    rtype = item.get("itemtype")
    pi = None
    if rtype == "riceball":
        qty = _safe_quantity(item)
        pi = menu_tool.quote_riceball_price(
            flavor=item.get("flavor"),
            large=item.get("large", False),
            heavy=item.get("heavy", False),
            extra_egg=item.get("extra_egg", False),
            quantity=qty,
        )
        # 表內加料（如加起司）併入單品價；待確認品項維持基礎價，由 price_pending 標記
        if pi.get("ok") and item.get("customization"):
            addon_total = _riceball_addon_quote(item)
            if addon_total:
                pi["total_price"] += addon_total * qty
    elif rtype == "egg_pancake":
        pi = egg_pancake_tool.quote_egg_pancake_price(item)
    elif rtype == "carrier":
        pi = carrier_tool.quote_carrier_price(item)
    elif rtype == "drink":
        pi = drink_tool.quote_drink_price(item)
    elif rtype == "snack":
        pi = snack_tool.quote_snack_price(item)
    elif rtype == "jam_toast":
        pi = jam_toast_tool.quote_jam_toast_price(item)
    elif rtype == "combo":
        pi = combo_tool.quote_combo_price(item)
    return pi


def extract_total(pi: Dict[str, Any]) -> int:
    """取出報價總價。數量只在各 quote 函式內乘一次，此處不得再乘。"""
    if not pi:
        return 0
    total = pi.get("total_price")
    if total is not None:
        return total
    return 0


# 客製化中代表「加料/換料」的訊號詞（會改變價格 → 需店員確認）
_ADD_SIGNALS = ("加", "多", "換", "雙", "額外", "加料")
# 否定前綴：「不加」「沒加」等代表的是減料，不算加料
_ADD_NEGATORS = ("不", "沒", "別", "免")
# 免費標準辣度選項（店家本來就提供、不加價）：先剝除避免「加辣菜脯」被誤判成加價加料
# 由長到短排序，確保「加辣菜脯」整段先被剝掉，不會殘留「加」字
_FREE_SPICY_PHRASES = ("加辣菜脯", "辣菜脯", "加辣", "辣")


def _strip_free_spicy(c: str) -> str:
    """剝除免費標準辣度選項片段。"""
    for phrase in _FREE_SPICY_PHRASES:
        c = c.replace(phrase, "")
    return c


def is_price_pending_customization(customization: Optional[str]) -> bool:
    """客製化是否需店員確認價格。

    含未被否定的「加/換/多」類客製（如「加起司」「換醬」）→ True。
    純減料偏好（「不要辣」「去掉香菜」）、免費辣度（「加辣菜脯」）或無客製 → False，不誤標。
    註：飯糰品項由 _riceball_addon_quote 先套加料表精準計價，
    本函式作為其餘品項與表外加料的 fallback 粗判。
    """
    if not customization:
        return False
    # 先剝除免費標準辣度選項，避免「加辣菜脯」被當成加價加料
    c = _strip_free_spicy(customization.strip())
    for sig in _ADD_SIGNALS:
        idx = c.find(sig)
        while idx != -1:
            prev = c[idx - 1] if idx > 0 else ""
            if prev not in _ADD_NEGATORS:
                return True
            idx = c.find(sig, idx + 1)
    return False


# 加料同義詞由長到短排序，長字先匹配並從字串移除，避免「加起司片」被「起司」重複吃到
_INGREDIENT_SYNS_SORTED = sorted(INGREDIENT_SYNONYMS, key=len, reverse=True)


def _riceball_addon_quote(item: Dict[str, Any]) -> Optional[int]:
    """解析飯糰 customization 的「加X」配料並套加料表計價。

    Returns:
        表內加料 → 加價金額（可為 0）；
        表外加料或殘留「換/多」等無法計價的訊號 → None（價格待確認）。
    """
    c = _strip_free_spicy((item.get("customization") or "").strip())
    add: List[str] = []
    for syn in _INGREDIENT_SYNS_SORTED:
        token = "加" + syn
        if token not in c:
            continue
        c = c.replace(token, "")
        # 加蛋已由 extra_egg 欄位加價，不重複計
        if INGREDIENT_SYNONYMS[syn] == "蛋" and item.get("extra_egg"):
            continue
        add.append(INGREDIENT_SYNONYMS[syn])
    # 殘留字串仍含加料訊號（換醬、多肉、加表外配料）→ 待確認
    if is_price_pending_customization(c):
        return None
    if not add:
        return 0
    quote = menu_tool.quote_riceball_customization_price(
        flavor=item.get("flavor") or "", add_ingredients=add
    )
    if not quote.get("ok") or quote.get("needs_store_confirm"):
        return None
    return quote["addon_total"]


def is_item_price_pending(item: Dict[str, Any]) -> bool:
    """購物車品項是否價格待確認（由 customization 推導，不另存欄位）。"""
    if item.get("itemtype") == "riceball" and item.get("customization"):
        return _riceball_addon_quote(item) is None
    return is_price_pending_customization(item.get("customization"))


def cart_has_pending(cart: List[Dict[str, Any]]) -> bool:
    """購物車是否含任何價格待確認品項。"""
    return any(is_item_price_pending(i) for i in cart)


def build_cart_summary(cart: List[Dict[str, Any]], price_format: str = "dollar") -> Dict[str, Any]:
    """將購物車 list 轉換為摘要結構。

    Args:
        cart: 購物車品項列表
        price_format: 價格字串格式，"dollar" → "$xxx"，"chinese" → "xxx元"

    Returns:
        {"items": [...], "total_price": int}
        每個 item：{"index": int, "name": str, "price_str": str, "quantity": int, "total": int}
    """
    items = []
    total_price = 0

    for i, item in enumerate(cart, 1):
        qty = _safe_quantity(item)
        name = format_item(item)
        pi = get_price_info(item)
        if pi and pi.get("ok"):
            item_total = extract_total(pi)
            total_price += item_total
            price_str = f"${item_total}" if price_format == "dollar" else f"{item_total}元"
        else:
            item_total = 0
            price_str = ""

        items.append(
            {
                "index": i,
                "item_id": item.get("item_id", ""),
                "name": name,
                "quantity": qty,
                "price_str": price_str,
                "total": item_total,
            }
        )

    return {"items": items, "total_price": total_price}


def calculate_cart_total(cart: List[Dict[str, Any]]) -> int:
    """計算購物車總價"""
    total = 0
    for item in cart:
        pi = get_price_info(item)
        if pi and pi.get("ok"):
            total += extract_total(pi)
    return total


def get_order_summary(cart: List[Dict[str, Any]]) -> str:
    """產生訂單摘要字串（同品項+同客製選項合併顯示 x數量）"""
    if not cart:
        return "目前沒有品項"

    # 先檢查所有品項是否可計價，同時快取價格資訊
    price_cache: Dict[int, Dict[str, Any]] = {}
    for item in cart:
        pi = get_price_info(item)
        if not pi or not pi.get("ok"):
            return f"品項「{format_item(item)}」無法計價：{pi.get('message', '計價失敗') if pi else '計價失敗'}。請洽服務人員再結帳。"
        price_cache[id(item)] = pi

    # 依品項唯一鍵分組，保持插入順序
    groups: OrderedDict = OrderedDict()
    for item in cart:
        key = _item_key(item)
        if key not in groups:
            groups[key] = {"item": item, "count": 0, "subtotal": 0}
        groups[key]["count"] += 1
        groups[key]["subtotal"] += extract_total(price_cache[id(item)])

    lines = []
    total_count = 0
    total_price = 0
    for g in groups.values():
        name = format_item(g["item"])
        lines.append(f"{name} x{g['count']}" if g["count"] > 1 else name)
        total_count += g["count"]
        total_price += g["subtotal"]

    if total_price == 0:
        return "抱歉，部分品項找不到價格資訊，請重新確認。"

    items_str = ", ".join(lines)
    return f"這樣一共{items_str}，共 {total_count} 個品項，共 {total_price}元"


def get_short_summary(cart: List[Dict[str, Any]]) -> str:
    """產生簡短摘要（用於刪除/取消後），同品項合併顯示 x數量"""
    if not cart:
        return "購物車是空的"
    # 依品項唯一鍵分組，保持插入順序
    groups: OrderedDict = OrderedDict()
    for item in cart:
        key = _item_key(item)
        if key not in groups:
            groups[key] = {"item": item, "count": 0}
        groups[key]["count"] += 1
    parts = []
    for g in groups.values():
        name = format_item(g["item"])
        parts.append(f"{name} x{g['count']}" if g["count"] > 1 else name)
    return "、".join(parts)


def cancel_last(session: Dict[str, Any]) -> str:
    """取消最後一個品項"""
    if session["cart"]:
        item = session["cart"].pop()
        name = format_item(item)
        return f"好的，已取消您最後點的：{name}。{get_short_summary(session['cart'])}"
    return "目前沒有品項可以取消喔。"


def remove_by_index(session: Dict[str, Any], text: str) -> str:
    """根據序號刪除品項"""
    cart = session["cart"]
    if not cart:
        return "購物車目前是空的喔。"
    idx = parse_index(text)
    if idx is None:
        return f"抱歉，我不確定您要刪除第幾項。目前共有 {len(cart)} 項。"

    if 1 <= idx <= len(cart):
        removed = cart.pop(idx - 1)
        name = format_item(removed)
        return f"好的，已為您刪除第 {idx} 項：{name}。{get_short_summary(cart)}"
    return f"目前只有 {len(cart)} 項品項，請確認要刪除第幾項。"


def cancel_generic(session: Dict[str, Any]) -> str:
    """通用取消邏輯"""
    if session["pending_frames"]:
        removed = session["pending_frames"].pop(0)
        if removed.get("_is_combo_sub_item"):
            session.pop("current_combo_frame", None)
            session["pending_frames"] = [
                f for f in session["pending_frames"] if not f.get("_is_combo_sub_item")
            ]
        return "好的，已取消剛剛的變更或品項。還需要什麼嗎？"
    if session.get("pending_clear_confirm"):
        session.pop("pending_clear_confirm")
        return "好的，已取消清空操作。還需要什麼嗎？"
    return cancel_last(session)


def parse_index(text: str) -> Optional[int]:
    """從文字中解析序號"""
    patterns = [
        r"第\s*(\d+|[一二三四五六七八九十]+)\s*(?:項|個|份)?",
        r"(\d+|[一二三四五六七八九十]+)\s*(?:項|個|份)",
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            token = m.group(1)
            return int(token) if token.isdigit() else chinese_number_to_int(token)
    return None
