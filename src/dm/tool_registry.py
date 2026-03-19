"""工具註冊表 - 管理 LLM 可調用的工具"""

from typing import Dict, Any, List, Callable, Optional, Set
from src.dm.dialogue_manager import DialogueManager
from src.dm.session_store import InMemorySessionStore
from src.dm import cart_manager
from src.tools.menu import menu_price_service, menu_state_service

# 導入各工具的別名映射
from src.tools.riceball_tool import FLAVOR_ALIASES as RICEBALL_ALIASES
from src.tools.drink_tool import (
    DRINK_ALIASES,
    SIZE_MAP as DRINK_SIZE_MAP,
    TEMP_MAP as DRINK_TEMP_MAP,
)
from src.tools.egg_pancake_tool import EggPancakeTool
from src.tools.snack_tool import SNACK_ALIASES
from src.dm.item_rules import check_combo_required
import asyncio
from datetime import datetime
from src.api.order_broadcaster import order_broadcaster, format_order_for_admin
from src.repository.order_repository import order_repo

# 蛋餅別名
EGG_PANCAKE_ALIASES = EggPancakeTool.FLAVOR_ALIASES

# 結帳正規化映射（finalize_order / preview_checkout 共用）
_DINE_TYPE_MAP: Dict[str, str] = {
    "內用": "dine-in",
    "外帶": "take-out",
    "dine-in": "dine-in",
    "take-out": "take-out",
}
_PAYMENT_MAP: Dict[str, str] = {
    "現金": "cash",
    "行動支付": "line_pay",
    "Line Pay": "line_pay",
    "cash": "cash",
    "mobile": "line_pay",
    "line_pay": "line_pay",
}


class ToolRegistry:
    """
    工具註冊表 - 提供 OpenAI Function Calling 格式的工具定義、執行映射和參數驗證
    """

    def __init__(self, dialogue_manager: DialogueManager, session_store: InMemorySessionStore):
        """
        初始化工具註冊表

        Args:
            dialogue_manager: DialogueManager 實例
            session_store: SessionStore 實例
        """
        self.dm = dialogue_manager
        self.store = session_store
        self._session_id: Optional[str] = None

    def set_session_id(self, session_id: str) -> None:
        """設置當前會話 ID"""
        self._session_id = session_id

    def get_current_session(self) -> Dict[str, Any]:
        """取得當前會話"""
        if not self._session_id:
            raise RuntimeError("Session ID not set")
        return self.store.get(self._session_id)

    # ============ 別名解析輔助方法 ============

    def _resolve_alias(
        self, value: Optional[str], aliases: dict, sort_by_len: bool = True
    ) -> Optional[str]:
        """通用別名解析：在 aliases 中找匹配項，回傳標準名稱；無匹配則原樣回傳"""
        if value is None:
            return None
        candidates = (
            sorted(aliases.keys(), key=len, reverse=True) if sort_by_len else list(aliases.keys())
        )
        for alias in candidates:
            if alias == value or alias in value:
                return aliases[alias]
        return value

    def _resolve_riceball_flavor(self, flavor: Optional[str]) -> Optional[str]:
        """將飯糰口味別名轉換為標準名稱"""
        return self._resolve_alias(flavor, RICEBALL_ALIASES)

    def _resolve_drink_flavor(self, flavor: Optional[str]) -> Optional[str]:
        """將飲料別名轉換為標準名稱"""
        return self._resolve_alias(flavor, DRINK_ALIASES)

    def _resolve_drink_size(self, size: Optional[str]) -> Optional[str]:
        """將飲料杯型轉換為標準名稱"""
        return self._resolve_alias(size, DRINK_SIZE_MAP, sort_by_len=False)

    def _resolve_drink_temp(self, temp: Optional[str]) -> Optional[str]:
        """將飲料溫度轉換為標準名稱"""
        return self._resolve_alias(temp, DRINK_TEMP_MAP, sort_by_len=False)

    def _resolve_egg_pancake_flavor(self, flavor: Optional[str]) -> Optional[str]:
        """將蛋餅口味別名轉換為標準名稱"""
        return self._resolve_alias(flavor, EGG_PANCAKE_ALIASES)

    def _resolve_snack_flavor(self, flavor: Optional[str]) -> Optional[str]:
        """將點心別名轉換為標準名稱"""
        return self._resolve_alias(flavor, SNACK_ALIASES)

    def _next_item_id(self, session: Dict[str, Any], prefix: str) -> str:
        """分配下一個 item_id，同時遞增計數器"""
        counter = session.get("cart_id_counter", 0) + 1
        session["cart_id_counter"] = counter
        return f"{prefix}_{counter}"

    # ============ 品項專屬工具 ============

    def add_riceball(
        self,
        flavor: Optional[str] = None,
        rice: Optional[str] = None,
        large: bool = False,
        extra_egg: bool = False,
        spicy: bool = False,
        quantity: int = 1,
        customization: Optional[str] = None,
    ) -> Dict[str, Any]:
        """加入飯糰到購物車。flavor（口味）和 rice（米種）都必填。"""
        try:
            # 缺欄位檢查
            missing = []
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

            session = self.get_current_session()
            resolved_flavor = self._resolve_riceball_flavor(flavor)
            item_id = self._next_item_id(session, "riceball")

            item: Dict[str, Any] = {
                "item_id": item_id,
                "itemtype": "riceball",
                "flavor": resolved_flavor,
                "rice": rice,
                "large": bool(large),
                "extra_egg": bool(extra_egg),
                "spicy": bool(spicy),
                "quantity": max(1, quantity),
            }
            if customization:
                item["customization"] = customization

            session["cart"].append(item)

            display_name = f"{rice}{resolved_flavor}"
            return {
                "ok": True,
                "item_id": item_id,
                "message": f"已加入 {quantity}份 {display_name}",
                "cart_count": len(session["cart"]),
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def add_drink(
        self,
        flavor: Optional[str] = None,
        size: Optional[str] = None,
        temp: Optional[str] = None,
        quantity: int = 1,
        customization: Optional[str] = None,
    ) -> Dict[str, Any]:
        """加入飲料到購物車。flavor（品項）、size（杯型）、temp（溫度）都必填。"""
        try:
            missing = []
            if not flavor:
                missing.append("flavor")
            if not size:
                missing.append("size")
            if not temp:
                missing.append("temp")
            if missing:
                parts = []
                if "flavor" in missing:
                    parts.append("飲料品項")
                if "size" in missing or "temp" in missing:
                    parts.append("規格（中冰/中溫/大冰/大溫）")
                msg = f"請問{' 和 '.join(parts)}？"
                return {"ok": False, "missing": missing, "message": msg}

            session = self.get_current_session()
            resolved_flavor = self._resolve_drink_flavor(flavor)
            resolved_size = self._resolve_drink_size(size)
            resolved_temp = self._resolve_drink_temp(temp)
            item_id = self._next_item_id(session, "drink")

            item: Dict[str, Any] = {
                "item_id": item_id,
                "itemtype": "drink",
                "drink": resolved_flavor,
                "size": resolved_size,
                "temp": resolved_temp,
                "quantity": max(1, quantity),
            }
            if customization:
                item["customization"] = customization

            session["cart"].append(item)

            display_name = f"{resolved_size}{resolved_temp}{resolved_flavor}"
            return {
                "ok": True,
                "item_id": item_id,
                "message": f"已加入 {quantity}份 {display_name}",
                "cart_count": len(session["cart"]),
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def add_carrier(
        self,
        carrier: Optional[str] = None,
        flavor: Optional[str] = None,
        quantity: int = 1,
        customization: Optional[str] = None,
    ) -> Dict[str, Any]:
        """加入吐司/漢堡/饅頭系列到購物車。carrier（載體）和 flavor（餡料）都必填。"""
        try:
            missing = []
            if not carrier:
                missing.append("carrier")
            if not flavor:
                missing.append("flavor")
            if missing:
                parts = []
                if "carrier" in missing:
                    parts.append("載體類型（吐司/漢堡/饅頭）")
                if "flavor" in missing:
                    parts.append("餡料口味")
                msg = f"請問{' 和 '.join(parts)}？"
                return {"ok": False, "missing": missing, "message": msg}

            session = self.get_current_session()
            item_id = self._next_item_id(session, "carrier")

            item: Dict[str, Any] = {
                "item_id": item_id,
                "itemtype": "carrier",
                "carrier": carrier,
                "flavor": flavor,
                "quantity": max(1, quantity),
            }
            if customization:
                item["customization"] = customization

            session["cart"].append(item)

            display_name = f"{flavor}{carrier}"
            return {
                "ok": True,
                "item_id": item_id,
                "message": f"已加入 {quantity}份 {display_name}",
                "cart_count": len(session["cart"]),
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def add_egg_pancake(
        self,
        flavor: Optional[str] = None,
        quantity: int = 1,
        customization: Optional[str] = None,
    ) -> Dict[str, Any]:
        """加入蛋餅到購物車。flavor（口味）必填。"""
        try:
            if not flavor:
                return {"ok": False, "missing": ["flavor"], "message": "請問蛋餅要什麼口味？"}

            session = self.get_current_session()
            resolved_flavor = self._resolve_egg_pancake_flavor(flavor)
            item_id = self._next_item_id(session, "egg_pancake")

            item: Dict[str, Any] = {
                "item_id": item_id,
                "itemtype": "egg_pancake",
                "flavor": resolved_flavor,
                "quantity": max(1, quantity),
            }
            if customization:
                item["customization"] = customization

            session["cart"].append(item)

            return {
                "ok": True,
                "item_id": item_id,
                "message": f"已加入 {quantity}份 {resolved_flavor}",
                "cart_count": len(session["cart"]),
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def add_snack(
        self,
        flavor: Optional[str] = None,
        quantity: int = 1,
        customization: Optional[str] = None,
    ) -> Dict[str, Any]:
        """加入點心到購物車。flavor（品項名稱）必填。"""
        try:
            if not flavor:
                return {"ok": False, "missing": ["flavor"], "message": "請問要什麼點心？"}

            session = self.get_current_session()
            resolved_flavor = self._resolve_snack_flavor(flavor)
            item_id = self._next_item_id(session, "snack")

            item: Dict[str, Any] = {
                "item_id": item_id,
                "itemtype": "snack",
                "snack": resolved_flavor,
                "quantity": max(1, quantity),
            }
            if customization:
                item["customization"] = customization

            session["cart"].append(item)

            return {
                "ok": True,
                "item_id": item_id,
                "message": f"已加入 {quantity}份 {resolved_flavor}",
                "cart_count": len(session["cart"]),
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def add_combo(
        self,
        combo_name: Optional[str] = None,
        rice: Optional[str] = None,
        temp: Optional[str] = None,
        flavor: Optional[str] = None,
        customization: Optional[str] = None,
        quantity: int = 1,
    ) -> Dict[str, Any]:
        """加入套餐到購物車。combo_name 必填，其他依套餐要求。"""
        try:
            if not combo_name:
                return {"ok": False, "missing": ["combo_name"], "message": "請問要哪個套餐？"}

            # 用現有函式檢查套餐必填欄位
            missing_msg = check_combo_required(combo_name, temp, flavor, rice, customization)
            if missing_msg:
                return {"ok": False, "message": missing_msg}

            session = self.get_current_session()
            item_id = self._next_item_id(session, "combo")

            item: Dict[str, Any] = {
                "item_id": item_id,
                "itemtype": "combo",
                "combo_name": combo_name,
                "quantity": max(1, quantity),
            }
            if temp:
                item["drink_temp"] = temp
            if rice:
                item["rice"] = rice
            if flavor:
                item["sub_flavor"] = flavor
            if customization:
                item["customization"] = customization

            session["cart"].append(item)

            msg = f"已加入 {quantity}份 {combo_name}"
            if customization:
                msg += f"（{customization}）"
            return {
                "ok": True,
                "item_id": item_id,
                "message": msg,
                "cart_count": len(session["cart"]),
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def update_draft(self, items: list) -> Dict[str, Any]:
        """直接覆蓋 session draft（待確認品項，不分配 item_id）。"""
        try:
            session = self.get_current_session()
            session["draft"] = list(items)
            return {
                "ok": True,
                "draft_count": len(items),
                "message": f"已記錄 {len(items)} 項待確認品項",
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def modify_cart_item(self, item_id: str, field: str, new_value: Any) -> Dict[str, Any]:
        """直接修改購物車中某品項的欄位值。需要 item_id（從 get_cart_summary 取得）。"""
        try:
            session = self.get_current_session()
            cart = session.get("cart", [])

            for item in cart:
                if item.get("item_id") == item_id:
                    item[field] = new_value
                    return {"ok": True, "message": f"已修改 {item_id}.{field} = {new_value}"}

            return {"ok": False, "message": f"找不到 item_id={item_id}"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ============ 原有工具（backward compat，保留方法本體） ============

    def add_to_cart(
        self,
        item_type: str,
        flavor: Optional[str] = None,
        rice: Optional[str] = None,
        size: Optional[str] = None,
        temp: Optional[str] = None,
        carrier: Optional[str] = None,
        combo_name: Optional[str] = None,
        quantity: int = 1,
        large: bool = False,
        extra_egg: bool = False,
        spicy: bool = False,
        customization: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        添加品項到購物車（已廢棄，保留作 backward compat）

        Args:
            item_type: 品項類型 (riceball, drink, carrier, egg_pancake, jam_toast, snack, combo)
            flavor: 口味
            rice: 米種 (飯糰)
            size: 杯型 (飲料) / 厚度 (果醬吐司)
            temp: 溫度 (飲料)
            carrier: 載體類型 (吐司/漢堡/饅頭)
            combo_name: 套餐名稱
            quantity: 數量
            large: 是否加大 (飯糰)
            extra_egg: 是否加蛋 (飯糰)
            spicy: 是否加辣菜脯 (飯糰)
            customization: 客製化需求

        Returns:
            操作結果
        """
        try:
            session = self.get_current_session()

            # 構建品項框架
            item: Dict[str, Any] = {
                "itemtype": item_type,
                "quantity": max(1, quantity),
            }

            # 根據品項類型填充字段（使用別名解析）
            if item_type == "riceball":
                resolved_flavor = self._resolve_riceball_flavor(flavor)
                if resolved_flavor:
                    item["flavor"] = resolved_flavor
                if rice:
                    item["rice"] = rice
                item["large"] = bool(large)
                item["extra_egg"] = bool(extra_egg)
                item["spicy"] = bool(spicy)

            elif item_type == "drink":
                resolved_flavor = self._resolve_drink_flavor(flavor)
                resolved_size = self._resolve_drink_size(size)
                resolved_temp = self._resolve_drink_temp(temp)
                if resolved_flavor:
                    item["drink"] = resolved_flavor
                if resolved_temp:
                    item["temp"] = resolved_temp
                if resolved_size:
                    item["size"] = resolved_size

            elif item_type == "carrier":
                if carrier:
                    item["carrier"] = carrier
                if flavor:
                    item["flavor"] = flavor  # 載體的 flavor 通常是完整的（如「豬肉蛋」）

            elif item_type == "egg_pancake":
                resolved_flavor = self._resolve_egg_pancake_flavor(flavor)
                if resolved_flavor:
                    item["flavor"] = resolved_flavor

            elif item_type == "jam_toast":
                if flavor:
                    item["flavor"] = flavor
                    resolved_size = size or "薄片"
                    item["jam_toast"] = f"果醬吐司({flavor}/{resolved_size})"
                if size:
                    item["size"] = size

            elif item_type == "snack":
                resolved_flavor = self._resolve_snack_flavor(flavor)
                if resolved_flavor:
                    item["snack"] = resolved_flavor

            elif item_type == "combo":
                if combo_name:
                    item["combo_name"] = combo_name
                # 檢查套餐必填欄位
                missing = check_combo_required(combo_name, temp, flavor, rice, customization)
                if missing:
                    return {"ok": False, "message": missing}
                # 存入追問答案
                if temp:
                    item["drink_temp"] = temp
                if rice:
                    item["rice"] = rice
                if flavor:
                    item["sub_flavor"] = flavor

            # 添加客製化需求
            if customization:
                item["customization"] = customization

            # 添加到購物車
            session["cart"].append(item)

            # 構建確認信息（使用解析後的值）
            if item_type == "riceball":
                display_flavor = item.get("flavor", "飯糰")
                display_rice = item.get("rice", "")
                display_name = f"{display_rice}{display_flavor}" if display_rice else display_flavor
            elif item_type == "drink":
                display_flavor = item.get("drink", "飲料")
                display_size = item.get("size", "")
                display_temp = item.get("temp", "")
                display_name = f"{display_size}{display_temp}{display_flavor}"
            elif item_type == "carrier" and carrier:
                display_name = f"{item.get('flavor', '')}{carrier}"
            elif item_type == "egg_pancake":
                display_name = item.get("flavor", "蛋餅")
            elif item_type == "snack":
                display_name = item.get("snack", "點心")
            elif item_type == "combo":
                display_name = combo_name or "套餐"
            else:
                display_name = flavor or combo_name or item_type

            return {
                "ok": True,
                "message": f"已添加 {quantity} 份 {display_name}",
                "cart_count": len(session["cart"]),
            }

        except Exception as e:
            return {"ok": False, "error": str(e)}

    def remove_from_cart(
        self,
        index: Optional[int] = None,
        item_id: Optional[str] = None,
        last: bool = False,
        all: bool = False,
    ) -> Dict[str, Any]:
        """
        從購物車移除品項

        Args:
            index: 要移除的品項索引（1 開始）
            item_id: 要移除的品項 ID（優先）
            last: 是否移除最後一項
            all: 是否清空購物車

        Returns:
            操作結果
        """
        try:
            session = self.get_current_session()
            cart = session["cart"]

            if not cart:
                return {"ok": False, "message": "購物車目前是空的"}

            if all:
                session["cart"] = []
                return {"ok": True, "message": "已清空購物車"}

            # item_id 優先
            if item_id is not None:
                for i, item in enumerate(cart):
                    if item.get("item_id") == item_id:
                        cart.pop(i)
                        return {
                            "ok": True,
                            "message": f"已移除 {item_id}",
                            "cart_count": len(cart),
                        }
                return {"ok": False, "message": f"找不到 item_id={item_id}"}

            if last:
                cart.pop()
                return {
                    "ok": True,
                    "message": "已移除最後一項",
                    "cart_count": len(cart),
                }

            if index is not None:
                if 1 <= index <= len(cart):
                    cart.pop(index - 1)
                    return {
                        "ok": True,
                        "message": f"已移除第 {index} 項",
                        "cart_count": len(cart),
                    }
                else:
                    return {
                        "ok": False,
                        "message": f"索引超出範圍，購物車共有 {len(cart)} 項",
                    }

            return {"ok": False, "message": "請指定要移除的品項"}

        except Exception as e:
            return {"ok": False, "error": str(e)}

    def get_cart_summary(self) -> Dict[str, Any]:
        """
        取得購物車摘要（含 item_id 和 draft_items）

        Returns:
            購物車摘要
        """
        try:
            session = self.get_current_session()
            cart = session.get("cart", [])
            draft = session.get("draft", [])

            if not cart and not draft:
                return {
                    "ok": True,
                    "cart_count": 0,
                    "items": [],
                    "draft_items": [],
                    "total_price": 0,
                    "message": "購物車為空",
                }

            # 使用共用 build_cart_summary 計算 cart items
            summary = cart_manager.build_cart_summary(cart, price_format="chinese")
            items = [
                {
                    "item_id": cart[entry["index"] - 1].get("item_id", ""),
                    "index": entry["index"],
                    "name": entry["name"],
                    "quantity": entry["quantity"],
                    "price": entry["price_str"],
                }
                for entry in summary["items"]
            ]
            total_price = summary["total_price"]

            # 格式化 draft 品項
            draft_items = [
                {
                    "index": i,
                    "name": cart_manager.format_item(item),
                    "status": "待確認",
                }
                for i, item in enumerate(draft, 1)
            ]

            return {
                "ok": True,
                "cart_count": len(cart),
                "items": items,
                "draft_items": draft_items,
                "total_price": total_price,
                "message": f"購物車共 {len(cart)} 項，總計 {total_price} 元",
            }

        except Exception as e:
            return {"ok": False, "error": str(e)}

    def query_menu(self, category: Optional[str] = None) -> Dict[str, Any]:
        """
        查詢菜單分類或品項。
        不指定 category 時回傳所有分類名稱；
        指定 category 時回傳該分類品項（含售罄狀態與價格）；
        分類為「飯糰」時額外附上成分表。

        Args:
            category: 菜單分類（飯糰、飲品、蛋餅等），不填則回傳所有分類

        Returns:
            {"ok": True, "categories": [...]} 或
            {"ok": True, "category": "...", "items": [...], "count": N}
        """
        try:
            menu_data = menu_price_service.get_raw_menu()

            if not category:
                # 回傳所有分類名稱
                categories: Set[str] = set()
                for item in menu_data:
                    if item.get("category"):
                        categories.add(item["category"])

                return {
                    "ok": True,
                    "categories": sorted(list(categories)),
                    "message": f"菜單共有 {len(categories)} 個分類",
                }

            # 回傳特定分類品項（含售罄狀態）
            sold_out = set(menu_state_service.get_effective_sold_out())
            items = [
                {
                    "name": item.get("name"),
                    "price": item.get("price"),
                    "available": item.get("name") not in sold_out,
                }
                for item in menu_data
                if item.get("category") == category
            ]

            if not items:
                return {
                    "ok": False,
                    "message": f"找不到分類「{category}」",
                }

            result: Dict[str, Any] = {
                "ok": True,
                "category": category,
                "items": items,
                "count": len(items),
                "message": f"{category}共有 {len(items)} 項",
            }

            # 飯糰分類額外附上成分表（幫助確認客人所說俗稱）
            if category == "飯糰":
                import json as _json
                import os as _os

                recipes_path = _os.path.join(
                    _os.path.dirname(_os.path.abspath(__file__)),
                    "..",
                    "tools",
                    "menu",
                    "riceball_recipes.json",
                )
                try:
                    with open(recipes_path, encoding="utf-8") as _f:
                        result["recipes"] = _json.load(_f)
                except Exception:
                    pass  # 成分表讀取失敗不影響主流程

            return result

        except Exception as e:
            return {"ok": False, "error": str(e)}

    def finalize_order(
        self,
        dine_type: str,
        payment_method: str,
    ) -> Dict[str, Any]:
        """
        完成結帳 — 由 LLM 收集完用餐方式和付款方式後呼叫

        Args:
            dine_type: 用餐方式 (dine-in / take-out)
            payment_method: 付款方式 (cash / mobile)
        """
        try:
            session = self.get_current_session()
            cart = session.get("cart", [])

            if not cart:
                return {"ok": False, "message": "購物車為空，無法結帳"}

            # 驗證所有品項都能正確定價
            unpriceable_items = []
            for item in cart:
                pi = cart_manager.get_price_info(item)
                if not pi or pi.get("status") != "success":
                    unpriceable_items.append(cart_manager.format_item(item))
            if unpriceable_items:
                return {
                    "ok": False,
                    "message": f"以下品項無法計算價格，請確認後重試：{'、'.join(unpriceable_items)}",
                }

            # 正規化 dine_type / payment_method
            resolved_dine = _DINE_TYPE_MAP.get(dine_type, dine_type)
            resolved_payment = _PAYMENT_MAP.get(payment_method, payment_method)

            # 計算總價（複用現有 _calculate_cart_total）
            total_price = cart_manager.calculate_cart_total(session["cart"])

            # 建立訂單 payload（order_number 由 save_order_with_number 原子性取號）
            order_id = f"order-{self._session_id}-{datetime.now().timestamp()}"

            # 構建品項清單（給前端用）
            items_payload = []
            for item in cart:
                qty = int(item.get("quantity", 1) or 1)
                pi = cart_manager.get_price_info(item)
                item_total = cart_manager.extract_total(pi, qty)
                unit_price = item_total // qty if qty > 0 else 0
                items_payload.append(
                    {
                        "name": cart_manager.format_item(item),
                        "quantity": qty,
                        "unit_price": unit_price,
                        "subtotal": item_total,
                    }
                )

            order_payload = {
                "order_id": order_id,
                "session_id": self._session_id,
                "dine_type": resolved_dine,
                "payment_method": resolved_payment,
                "items": cart,
                "items_display": items_payload,
                "total_price": total_price,
                "status": "SUBMITTED",
                "created_at": datetime.now().isoformat(),
            }

            # 原子性取號 + 寫入 DB
            order_number = order_repo.save_order_with_number(order_payload, self._session_id)

            # SSE 廣播到 admin 訂單頁面
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(order_broadcaster.broadcast(format_order_for_admin(order_payload)))
            except RuntimeError:
                pass  # 沒有 running loop（CLI 模式）

            # 儲存對話紀錄（JSON 檔）
            llm_history = session.get("llm_history", [])
            order_repo.save_conversation_log_json(
                self._session_id, order_number, cart, total_price, resolved_dine, llm_history
            )

            # 標記 session 完成，清空購物車防止重複送單
            session["status"] = "SUBMITTED"
            session["order_payload"] = order_payload
            session["cart"] = []
            session["llm_history"] = []

            return {
                "ok": True,
                "order_number": order_number,
                "total": total_price,
                "item_count": len(cart),
                "items_display": items_payload,
                "dine_type": resolved_dine,
                "payment_method": resolved_payment,
            }

        except Exception as e:
            return {"ok": False, "error": str(e)}

    def preview_checkout(
        self,
        dine_type: str,
        payment_method: str,
    ) -> Dict[str, Any]:
        """
        預覽結帳資訊 — 送前端確認畫面，不實際結帳

        Args:
            dine_type: 用餐方式 (dine-in / take-out)
            payment_method: 付款方式 (cash / line_pay)
        """
        session = self.get_current_session()
        cart = session.get("cart", [])
        if not cart:
            return {"ok": False, "message": "購物車為空"}

        return {
            "ok": True,
            "preview": True,
            "dine_type": _DINE_TYPE_MAP.get(dine_type, dine_type),
            "payment_method": _PAYMENT_MAP.get(payment_method, payment_method),
        }

    # ============ Schema 和映射 ============

    def get_tools_schema(self) -> List[Dict[str, Any]]:
        """
        取得 OpenAI Function Calling 格式的工具 schema

        Returns:
            工具 schema 列表
        """
        return [
            {
                "type": "function",
                "function": {
                    "name": "add_riceball",
                    "description": "加入飯糰到購物車。當客人說「一個鮪魚飯糰白米」「紫米培根加辣」時調用。flavor（口味）和 rice（米種）都必填，缺一則追問。flavor 只填口味名稱不帶「飯糰」後綴。spicy 是 boolean。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "flavor": {
                                "type": "string",
                                "description": "飯糰口味，只填口味名稱，如：源味傳統、香燻培根、醬燒里肌、起司蛋、鮪魚蛋、鮭魚等",
                            },
                            "rice": {
                                "type": "string",
                                "enum": ["白米", "紫米", "混米"],
                                "description": "米種，必填",
                            },
                            "large": {
                                "type": "boolean",
                                "default": False,
                                "description": "是否加大",
                            },
                            "extra_egg": {
                                "type": "boolean",
                                "default": False,
                                "description": "是否加蛋",
                            },
                            "spicy": {
                                "type": "boolean",
                                "default": False,
                                "description": "是否加辣菜脯",
                            },
                            "quantity": {
                                "type": "integer",
                                "default": 1,
                                "description": "數量",
                            },
                            "customization": {
                                "type": "string",
                                "description": "客製化需求",
                            },
                        },
                        "required": ["flavor", "rice"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "add_drink",
                    "description": "加入飲料到購物車。當客人說「一杯大冰紅茶」「中杯溫豆漿」時調用。flavor（品項）、size（杯型）、temp（溫度）都必填。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "flavor": {
                                "type": "string",
                                "description": "飲料名稱，如：有糖豆漿、純鮮奶茶、紅茶拿鐵等",
                            },
                            "size": {
                                "type": "string",
                                "enum": ["中杯", "大杯"],
                                "description": "杯型，必填",
                            },
                            "temp": {
                                "type": "string",
                                "enum": ["冰", "溫", "熱"],
                                "description": "溫度，必填",
                            },
                            "quantity": {"type": "integer", "default": 1},
                            "customization": {"type": "string"},
                        },
                        "required": ["flavor", "size", "temp"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "add_carrier",
                    "description": "加入吐司/漢堡/饅頭系列到購物車。當客人說「火腿蛋吐司」「起司蛋漢堡」「黑糖饅頭夾蛋」時調用。carrier（載體）和 flavor（餡料）都必填。客人只說「饅頭夾蛋」未指定饅頭口味時要追問。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "carrier": {
                                "type": "string",
                                "enum": ["吐司", "漢堡", "饅頭"],
                                "description": "載體類型，必填",
                            },
                            "flavor": {
                                "type": "string",
                                "description": "餡料口味，如：豬肉蛋、火腿蛋、起司蛋等。若 carrier 為饅頭，flavor 指饅頭種類（黑糖饅頭/白饅頭/黑糖花捲/白花捲/芋頭饅頭），非餡料；未指定饅頭種類時須追問。",
                            },
                            "quantity": {"type": "integer", "default": 1},
                            "customization": {"type": "string"},
                        },
                        "required": ["carrier", "flavor"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "add_egg_pancake",
                    "description": "加入蛋餅到購物車。當客人說「一個起司蛋餅」「原味蛋餅」時調用。flavor（口味）必填。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "flavor": {
                                "type": "string",
                                "description": "蛋餅口味，如：原味、起司、培根、鮪魚等",
                            },
                            "quantity": {"type": "integer", "default": 1},
                            "customization": {"type": "string"},
                        },
                        "required": ["flavor"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "add_snack",
                    "description": "加入點心到購物車。當客人說「一份薯餅」「蘿蔔糕加蛋」「玉米鐵板麵」時調用。包含：薯餅、蘿蔔糕、韭菜餡餅、蔥抓餅、鐵板麵系列。flavor 必填，鐵板麵只填口味（如「玉米」「蘑菇」）。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "flavor": {
                                "type": "string",
                                "description": "點心名稱，如：薯餅、蘿蔔糕加蛋、韭菜餡餅、玉米（鐵板麵）、蘑菇（鐵板麵）等",
                            },
                            "quantity": {"type": "integer", "default": 1},
                            "customization": {"type": "string"},
                        },
                        "required": ["flavor"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "add_combo",
                    "description": "加入套餐到購物車。當客人說「套餐一」「二號餐」「兒童餐」時調用。combo_name 必填，call 後依 ok:false 訊息追問缺少的規格。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "combo_name": {
                                "type": "string",
                                "enum": [
                                    "套餐一",
                                    "套餐二",
                                    "套餐三",
                                    "套餐四",
                                    "套餐A",
                                    "套餐B",
                                    "兒童餐",
                                ],
                                "description": "套餐名稱，必填",
                            },
                            "rice": {"type": "string", "enum": ["白米", "紫米", "混米"]},
                            "temp": {"type": "string", "enum": ["冰", "溫", "熱"]},
                            "flavor": {"type": "string"},
                            "quantity": {"type": "integer", "default": 1},
                            "customization": {"type": "string"},
                        },
                        "required": ["combo_name"],
                    },
                },
            },
            # update_draft / modify_cart_item / remove_from_cart 從 schema 移除
            # 方法保留在 tool_map 供 voice_router 直接呼叫
            {
                "type": "function",
                "function": {
                    "name": "query_menu",
                    "description": "當客人問有什麼可以點、詢問菜單內容、或你不確定某品項是否存在時調用。回傳分類清單或指定分類的品項（含售罄狀態與價格）；飯糰分類額外附成分表。category 不填則回傳所有分類名稱。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "category": {
                                "type": "string",
                                "description": "菜單分類，如：飯糰、飲品、蛋餅、吐司、漢堡、饅頭、點心、果醬吐司、套餐等。不指定則回傳所有分類名稱",
                            },
                        },
                    },
                },
            },
        ]

    def get_tool_map(self) -> Dict[str, Callable[..., Dict[str, Any]]]:
        """
        取得工具名到函數的映射

        Returns:
            工具映射字典
        """
        return {
            # 品項專屬工具（新）
            "add_riceball": self.add_riceball,
            "add_drink": self.add_drink,
            "add_carrier": self.add_carrier,
            "add_egg_pancake": self.add_egg_pancake,
            "add_snack": self.add_snack,
            "add_combo": self.add_combo,
            "update_draft": self.update_draft,
            "modify_cart_item": self.modify_cart_item,
            # 共用工具
            "remove_from_cart": self.remove_from_cart,
            "get_cart_summary": self.get_cart_summary,
            "query_menu": self.query_menu,
            "finalize_order": self.finalize_order,
            "preview_checkout": self.preview_checkout,
            # backward compat（已廢棄，保留避免舊呼叫崩潰）
            "add_to_cart": self.add_to_cart,
        }

    def get_allowed_args(self) -> Dict[str, Set[str]]:
        """
        取得每個工具允許的參數集合

        Returns:
            參數映射字典
        """
        return {
            # 品項專屬工具（新）
            "add_riceball": {
                "flavor",
                "rice",
                "large",
                "extra_egg",
                "spicy",
                "quantity",
                "customization",
            },
            "add_drink": {"flavor", "size", "temp", "quantity", "customization"},
            "add_carrier": {"carrier", "flavor", "quantity", "customization"},
            "add_egg_pancake": {"flavor", "quantity", "customization"},
            "add_snack": {"flavor", "quantity", "customization"},
            "add_combo": {"combo_name", "rice", "temp", "flavor", "quantity", "customization"},
            "update_draft": {"items"},
            "modify_cart_item": {"item_id", "field", "new_value"},
            # 共用工具
            "remove_from_cart": {"index", "item_id", "last", "all"},
            "get_cart_summary": set(),
            "query_menu": {"category"},
            "finalize_order": {"dine_type", "payment_method"},
            "preview_checkout": {"dine_type", "payment_method"},
            # backward compat
            "add_to_cart": {
                "item_type",
                "flavor",
                "rice",
                "size",
                "temp",
                "carrier",
                "combo_name",
                "quantity",
                "large",
                "extra_egg",
                "spicy",
                "customization",
            },
        }
