import re
import uuid
from collections import OrderedDict
from datetime import datetime
from typing import Dict, Any, List, Optional

from src.tools.riceball_tool import menu_tool, _chinese_number_to_int
from src.tools.carrier_tool import carrier_tool
from src.tools.drink_tool import drink_tool
from src.tools.snack_tool import snack_tool
from src.tools.jam_toast_tool import jam_toast_tool
from src.tools.egg_pancake_tool import egg_pancake_tool
from src.tools.combo_tool import combo_tool
from src.repository.order_repository import order_repo


def format_item(frame: Dict[str, Any]) -> str:
    """格式化購物車品項為可讀字串"""
    rtype = frame.get("itemtype")
    if rtype == "drink":
        name = frame.get("drink", "飲料")
        details = [str(frame[k]) for k in ["size", "temp", "sugar"] if frame.get(k)]
        return f"{name}({', '.join(details)})" if details else name
    if rtype == "riceball":
        return f"{frame.get('rice', '')}{'·' if frame.get('rice') else ''}{frame.get('flavor', '飯糰')}"
    if rtype == "carrier":
        return f"{frame.get('flavor', '')}{frame.get('carrier', '餐點')}"
    if rtype == "egg_pancake":
        return frame.get("flavor", "蛋餅")
    if rtype == "snack":
        base = frame.get("snack", "點心")
        details = [
            v for v in [frame.get("egg_cook"), "不要胡椒" if frame.get("no_pepper") else None] if v
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
        return frame.get("combo_name", "套餐")
    return "未知品項"


def _item_key(frame: Dict[str, Any]) -> str:
    """提取品項唯一身份（品項類型+格式化名稱），用於合併判斷"""
    rtype = frame.get("recognized_type", frame.get("itemtype", ""))
    name = format_item(frame)
    return f"{rtype}:{name}"


def get_price_info(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """根據品項類型取得價格資訊"""
    rtype = item.get("itemtype")
    pi = None
    if rtype == "riceball":
        pi = menu_tool.quote_riceball_price(
            flavor=item.get("flavor"),
            large=item.get("large", False),
            heavy=item.get("heavy", False),
            extra_egg=item.get("extra_egg", False),
        )
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


def extract_total(pi: Dict[str, Any], qty: int) -> int:
    """從價格資訊和數量計算總價"""
    if not pi:
        return 0
    if "total_price" in pi and pi["total_price"] is not None:
        return pi["total_price"]
    if "single_total" in pi:
        return pi["single_total"] * qty
    if "single_price" in pi:
        return pi["single_price"] * qty
    return 0


def calculate_cart_total(cart: List[Dict[str, Any]]) -> int:
    """計算購物車總價"""
    total = 0
    for item in cart:
        qty = int(item.get("quantity", 1) or 1)
        pi = get_price_info(item)
        if pi and pi.get("status") == "success":
            total += extract_total(pi, qty)
    return total


def get_order_summary(cart: List[Dict[str, Any]]) -> str:
    """產生訂單摘要字串（同品項+同客製選項合併顯示 x數量）"""
    if not cart:
        return "目前沒有品項"

    # 先檢查所有品項是否可計價，同時快取價格資訊
    price_cache: Dict[int, Dict[str, Any]] = {}
    for item in cart:
        pi = get_price_info(item)
        if not pi or pi.get("status") != "success":
            return f"品項「{format_item(item)}」無法計價：{pi.get('message', '計價失敗') if pi else '計價失敗'}。請洽服務人員再結帳。"
        price_cache[id(item)] = pi

    # 依品項唯一鍵分組，保持插入順序
    groups: OrderedDict = OrderedDict()
    for item in cart:
        key = _item_key(item)
        if key not in groups:
            groups[key] = {"item": item, "count": 0, "subtotal": 0}
        groups[key]["count"] += 1
        groups[key]["subtotal"] += extract_total(price_cache[id(item)], 1)

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


def submit_order(session: Dict[str, Any]) -> str:
    """生成 Payload 並送出訂單"""
    order_id = f"SN-{datetime.now().strftime('%m%d')}-{str(uuid.uuid4())[:4].upper()}"
    total_price = calculate_cart_total(session["cart"])

    items_payload = []
    for item in session["cart"]:
        qty = int(item.get("quantity", 1) or 1)
        pi = get_price_info(item)
        item_total = extract_total(pi, qty)
        unit_price = item_total // qty if qty > 0 else 0

        items_payload.append(
            {
                "name": format_item(item),
                "quantity": qty,
                "unit_price": unit_price,
                "subtotal": item_total,
            }
        )

    order_payload = {
        "order_id": order_id,
        "status": "SUBMITTED",
        "created_at": datetime.now().isoformat(),
        "items": items_payload,
        "total_price": total_price,
        "raw_history": session.get("history", []),
    }

    session["order_payload"] = order_payload
    session["status"] = "SUBMITTED"

    # 落庫儲存（原子性取號 + 寫入）
    order_repo.save_order_with_number(order_payload, session.get("session_id", "unknown"))

    return f"好的，訂單已送出！您的訂單編號是 {order_id}，請至櫃檯結帳領取。"


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
            return int(token) if token.isdigit() else _chinese_number_to_int(token)
    return None
