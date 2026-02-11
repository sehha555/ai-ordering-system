"""工具註冊表 - 管理 LLM 可調用的工具"""
from typing import Dict, Any, List, Callable, Optional, Set
from src.dm.dialogue_manager import DialogueManager
from src.dm.session_store import InMemorySessionStore
from src.tools.menu import menu_price_service

# 導入各工具的別名映射
from src.tools.riceball_tool import FLAVOR_ALIASES as RICEBALL_ALIASES
from src.tools.drink_tool import DRINK_ALIASES, SIZE_MAP as DRINK_SIZE_MAP, TEMP_MAP as DRINK_TEMP_MAP
from src.tools.egg_pancake_tool import EggPancakeTool
from src.tools.snack_tool import SNACK_ALIASES

# 蛋餅別名
EGG_PANCAKE_ALIASES = EggPancakeTool.FLAVOR_ALIASES


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

    def _resolve_riceball_flavor(self, flavor: Optional[str]) -> Optional[str]:
        """將飯糰口味別名轉換為標準名稱"""
        if not flavor:
            return None
        # 長字優先匹配
        for alias in sorted(RICEBALL_ALIASES.keys(), key=len, reverse=True):
            if alias == flavor or alias in flavor:
                return RICEBALL_ALIASES[alias]
        return flavor

    def _resolve_drink_flavor(self, flavor: Optional[str]) -> Optional[str]:
        """將飲料別名轉換為標準名稱"""
        if not flavor:
            return None
        # 長字優先匹配
        for alias in sorted(DRINK_ALIASES.keys(), key=len, reverse=True):
            if alias == flavor or alias in flavor:
                return DRINK_ALIASES[alias]
        return flavor

    def _resolve_drink_size(self, size: Optional[str]) -> Optional[str]:
        """將飲料杯型轉換為標準名稱"""
        if not size:
            return None
        for alias, canonical in DRINK_SIZE_MAP.items():
            if alias == size or alias in size:
                return canonical
        # 已經是標準格式
        if size in ["大杯", "中杯"]:
            return size
        return size

    def _resolve_drink_temp(self, temp: Optional[str]) -> Optional[str]:
        """將飲料溫度轉換為標準名稱"""
        if not temp:
            return None
        for alias, canonical in DRINK_TEMP_MAP.items():
            if alias == temp or alias in temp:
                return canonical
        return temp

    def _resolve_egg_pancake_flavor(self, flavor: Optional[str]) -> Optional[str]:
        """將蛋餅口味別名轉換為標準名稱"""
        if not flavor:
            return None
        # 長字優先匹配
        for alias in sorted(EGG_PANCAKE_ALIASES.keys(), key=len, reverse=True):
            if alias == flavor or alias in flavor:
                return EGG_PANCAKE_ALIASES[alias]
        return flavor

    def _resolve_snack_flavor(self, flavor: Optional[str]) -> Optional[str]:
        """將點心別名轉換為標準名稱"""
        if not flavor:
            return None
        # 長字優先匹配
        for alias in sorted(SNACK_ALIASES.keys(), key=len, reverse=True):
            if alias == flavor or alias in flavor:
                return SNACK_ALIASES[alias]
        return flavor

    # ============ 工具實現 ============

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
        添加品項到購物車

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
            item = {
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
        last: bool = False,
        all: bool = False,
    ) -> Dict[str, Any]:
        """
        從購物車移除品項

        Args:
            index: 要移除的品項索引（1 開始）
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

            if last:
                removed = cart.pop()
                return {
                    "ok": True,
                    "message": f"已移除最後一項",
                    "cart_count": len(cart),
                }

            if index is not None:
                if 1 <= index <= len(cart):
                    removed = cart.pop(index - 1)
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
        取得購物車摘要

        Returns:
            購物車摘要
        """
        try:
            session = self.get_current_session()
            cart = session["cart"]

            if not cart:
                return {
                    "ok": True,
                    "cart_count": 0,
                    "items": [],
                    "message": "購物車為空",
                }

            items = []
            total_price = 0

            for i, item in enumerate(cart, 1):
                item_type = item.get("itemtype", "unknown")
                qty = item.get("quantity", 1)

                # 格式化品項名稱
                if item_type == "riceball":
                    name = f"{item.get('rice', '')}·{item.get('flavor', '飯糰')}"
                elif item_type == "drink":
                    name = f"{item.get('drink', '飲料')}({item.get('size', '')} {item.get('temp', '')})"
                elif item_type == "carrier":
                    name = f"{item.get('carrier', '載體')}·{item.get('flavor', '')}"
                else:
                    name = item.get("flavor") or item.get(item_type) or item_type

                # 計算價格
                price_info = self.dm._get_price_info(item)
                if price_info and price_info.get("status") == "success":
                    item_total = self.dm._extract_total_from_pi(price_info, qty)
                    total_price += item_total
                    price_str = f" {item_total}元"
                else:
                    price_str = ""

                items.append({
                    "index": i,
                    "name": name,
                    "quantity": qty,
                    "price": price_str,
                })

            return {
                "ok": True,
                "cart_count": len(cart),
                "items": items,
                "total_price": total_price,
                "message": f"購物車共 {len(cart)} 項，總計 {total_price} 元",
            }

        except Exception as e:
            return {"ok": False, "error": str(e)}

    def query_menu(self, category: Optional[str] = None) -> Dict[str, Any]:
        """
        查詢菜單

        Args:
            category: 菜單分類（飯糰、飲品、蛋餅等）

        Returns:
            菜單信息
        """
        try:
            menu_data = menu_price_service.get_raw_menu()

            if not category:
                # 返回所有分類
                categories = set()
                for item in menu_data:
                    if item.get("category"):
                        categories.add(item["category"])

                return {
                    "ok": True,
                    "categories": sorted(list(categories)),
                    "message": f"菜單共有 {len(categories)} 個分類",
                }

            # 返回特定分類的品項
            items = [
                {
                    "name": item.get("name"),
                    "price": item.get("price"),
                }
                for item in menu_data
                if item.get("category") == category
            ]

            if not items:
                return {
                    "ok": False,
                    "message": f"找不到分類「{category}」",
                }

            return {
                "ok": True,
                "category": category,
                "items": items,
                "count": len(items),
                "message": f"{category}共有 {len(items)} 項",
            }

        except Exception as e:
            return {"ok": False, "error": str(e)}

    def get_price(
        self,
        item_type: str,
        flavor: Optional[str] = None,
        rice: Optional[str] = None,
        size: Optional[str] = None,
        temp: Optional[str] = None,
        large: bool = False,
        extra_egg: bool = False,
    ) -> Dict[str, Any]:
        """
        查詢品項價格

        Args:
            item_type: 品項類型
            flavor: 口味
            rice: 米種（飯糰）
            size: 杯型（飲料）
            temp: 溫度（飲料）
            large: 是否加大（飯糰）
            extra_egg: 是否加蛋（飯糰）

        Returns:
            價格信息
        """
        try:
            # 根據品項類型解析別名
            resolved_flavor = flavor
            resolved_size = size
            resolved_temp = temp

            if item_type == "riceball":
                resolved_flavor = self._resolve_riceball_flavor(flavor)
            elif item_type == "drink":
                resolved_flavor = self._resolve_drink_flavor(flavor)
                resolved_size = self._resolve_drink_size(size)
                resolved_temp = self._resolve_drink_temp(temp)
            elif item_type == "egg_pancake":
                resolved_flavor = self._resolve_egg_pancake_flavor(flavor)
            elif item_type == "snack":
                resolved_flavor = self._resolve_snack_flavor(flavor)

            item = {
                "itemtype": item_type,
                "flavor": resolved_flavor,
                "rice": rice,
                "size": resolved_size,
                "temp": resolved_temp,
                "large": large,
                "extra_egg": extra_egg,
            }

            price_info = self.dm._get_price_info(item)

            if not price_info:
                return {
                    "ok": False,
                    "message": f"無法計算 {flavor or item_type} 的價格",
                }

            if price_info.get("status") != "success":
                return {
                    "ok": False,
                    "message": price_info.get("message", "價格計算失敗"),
                }

            return {
                "ok": True,
                "item": flavor or item_type,
                "price": price_info.get("total_price"),
                "details": price_info,
            }

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

            # 正規化 dine_type
            dine_type_map = {"內用": "dine-in", "外帶": "take-out", "dine-in": "dine-in", "take-out": "take-out"}
            resolved_dine = dine_type_map.get(dine_type, dine_type)

            # 正規化 payment_method
            payment_map = {"現金": "cash", "行動支付": "mobile", "cash": "cash", "mobile": "mobile"}
            resolved_payment = payment_map.get(payment_method, payment_method)

            # 計算總價（複用現有 _calculate_cart_total）
            total_price = self.dm._calculate_cart_total(session)

            # 生成取餐號碼（複用 order_repo）
            from src.repository.order_repository import order_repo
            order_number = order_repo.get_next_order_number()

            # 建立訂單 payload
            from datetime import datetime
            order_id = f"order-{self._session_id}-{datetime.now().timestamp()}"

            # 構建品項清單（給前端用）
            items_payload = []
            for item in cart:
                qty = int(item.get("quantity", 1) or 1)
                pi = self.dm._get_price_info(item)
                item_total = self.dm._extract_total_from_pi(pi, qty)
                unit_price = item_total // qty if qty > 0 else 0
                items_payload.append({
                    "name": self.dm._format_item(item),
                    "quantity": qty,
                    "unit_price": unit_price,
                    "subtotal": item_total,
                })

            order_payload = {
                "order_id": order_id,
                "session_id": self._session_id,
                "order_number": order_number,
                "dine_type": resolved_dine,
                "payment_method": resolved_payment,
                "items": cart,
                "items_display": items_payload,
                "total_price": total_price,
                "status": "submitted",
                "created_at": datetime.now().isoformat(),
            }

            # 寫入 DB
            order_repo.save_order(order_payload, self._session_id)

            # 儲存對話紀錄
            llm_history = session.get("llm_history", [])
            order_repo.save_conversation_log(self._session_id, order_number, llm_history)
            order_repo.save_conversation_log_json(
                self._session_id, order_number, cart, total_price, resolved_dine, llm_history
            )

            # 標記 session 完成
            session["status"] = "SUBMITTED"
            session["order_payload"] = order_payload

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
                    "name": "add_to_cart",
                    "description": "添加品項到購物車。飯糰需要口味+米種，飲料需要品項+杯型+溫度，蛋餅/吐司/漢堡/饅頭需要口味，套餐需要套餐名。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "item_type": {
                                "type": "string",
                                "enum": ["riceball", "drink", "carrier", "egg_pancake", "jam_toast", "snack", "combo"],
                                "description": "品項類型：riceball(飯糰)、drink(飲料)、carrier(吐司/漢堡/饅頭)、egg_pancake(蛋餅)、jam_toast(果醬吐司)、snack(點心)、combo(套餐)",
                            },
                            "flavor": {
                                "type": "string",
                                "description": "品項口味或名稱。飯糰如：源味傳統、香燻培根、醬燒里肌。飲料如：有糖豆漿、純鮮奶茶。蛋餅如：原味蛋餅、起司蛋餅。載體如：豬肉蛋、火腿蛋。",
                            },
                            "rice": {
                                "type": "string",
                                "enum": ["白米", "紫米", "混米"],
                                "description": "米種 - 飯糰專用，必填",
                            },
                            "size": {
                                "type": "string",
                                "description": "飲料杯型(中杯/大杯)或果醬吐司厚度(薄片/厚片)",
                            },
                            "temp": {
                                "type": "string",
                                "enum": ["冰", "溫", "熱"],
                                "description": "溫度 - 飲料專用，必填",
                            },
                            "carrier": {
                                "type": "string",
                                "enum": ["吐司", "漢堡", "饅頭"],
                                "description": "載體類型 - 吐司/漢堡/饅頭專用",
                            },
                            "combo_name": {
                                "type": "string",
                                "description": "套餐名稱如：套餐一、套餐A、兒童餐 - 套餐專用",
                            },
                            "quantity": {
                                "type": "integer",
                                "description": "數量，預設 1",
                                "default": 1,
                            },
                            "large": {
                                "type": "boolean",
                                "description": "是否加大 - 飯糰用",
                                "default": False,
                            },
                            "extra_egg": {
                                "type": "boolean",
                                "description": "是否加蛋 - 飯糰用",
                                "default": False,
                            },
                            "spicy": {
                                "type": "boolean",
                                "description": "是否加辣菜脯 - 飯糰用",
                                "default": False,
                            },
                            "customization": {
                                "type": "string",
                                "description": "客製化需求，如：不要小黃瓜、不要醬油膏、裝一起、不要切等",
                            },
                        },
                        "required": ["item_type"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "remove_from_cart",
                    "description": "從購物車移除品項",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "index": {
                                "type": "integer",
                                "description": "品項索引（1 開始），不能與 last 或 all 同時使用",
                            },
                            "last": {
                                "type": "boolean",
                                "description": "是否移除最後一項",
                                "default": False,
                            },
                            "all": {
                                "type": "boolean",
                                "description": "是否清空購物車",
                                "default": False,
                            },
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_cart_summary",
                    "description": "取得購物車摘要，包括品項列表和總價",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "query_menu",
                    "description": "查詢菜單，可選擇指定分類或查看所有分類",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "category": {
                                "type": "string",
                                "description": "菜單分類（飯糰、飲品、蛋餅等），不指定則返回所有分類",
                            },
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_price",
                    "description": "查詢品項價格",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "item_type": {
                                "type": "string",
                                "description": "品項類型",
                            },
                            "flavor": {
                                "type": "string",
                                "description": "口味或品項名稱",
                            },
                            "rice": {
                                "type": "string",
                                "description": "米種 (紫米/白米/混米)",
                            },
                            "size": {
                                "type": "string",
                                "description": "杯型 (中杯/大杯)",
                            },
                            "temp": {
                                "type": "string",
                                "description": "溫度 (冰的/溫的)",
                            },
                            "large": {
                                "type": "boolean",
                                "description": "是否加大",
                                "default": False,
                            },
                            "extra_egg": {
                                "type": "boolean",
                                "description": "是否加蛋",
                                "default": False,
                            },
                        },
                        "required": ["item_type"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "finalize_order",
                    "description": "完成結帳並送出訂單。在確認客人點完餐、問完內用外帶、問完付款方式後才能調用。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "dine_type": {
                                "type": "string",
                                "enum": ["dine-in", "take-out", "內用", "外帶"],
                                "description": "用餐方式：內用或外帶",
                            },
                            "payment_method": {
                                "type": "string",
                                "enum": ["cash", "mobile", "現金", "行動支付"],
                                "description": "付款方式：現金或行動支付",
                            },
                        },
                        "required": ["dine_type", "payment_method"],
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
            "add_to_cart": self.add_to_cart,
            "remove_from_cart": self.remove_from_cart,
            "get_cart_summary": self.get_cart_summary,
            "query_menu": self.query_menu,
            "get_price": self.get_price,
            "finalize_order": self.finalize_order,
        }

    def get_allowed_args(self) -> Dict[str, Set[str]]:
        """
        取得每個工具允許的參數集合

        Returns:
            參數映射字典
        """
        return {
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
            "remove_from_cart": {"index", "last", "all"},
            "get_cart_summary": set(),
            "query_menu": {"category"},
            "get_price": {
                "item_type",
                "flavor",
                "rice",
                "size",
                "temp",
                "large",
                "extra_egg",
            },
            "finalize_order": {"dine_type", "payment_method"},
        }
