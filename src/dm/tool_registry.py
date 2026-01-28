"""工具註冊表 - 管理 LLM 可調用的工具"""
from typing import Dict, Any, List, Callable, Optional, Set
from src.dm.dialogue_manager import DialogueManager
from src.dm.session_store import InMemorySessionStore
from src.tools.menu import menu_price_service


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

    # ============ 工具實現 ============

    def add_to_cart(
        self,
        item_type: str,
        flavor: Optional[str] = None,
        rice: Optional[str] = None,
        size: Optional[str] = None,
        temp: Optional[str] = None,
        quantity: int = 1,
        large: bool = False,
        extra_egg: bool = False,
    ) -> Dict[str, Any]:
        """
        添加品項到購物車

        Args:
            item_type: 品項類型 (riceball, drink, carrier, egg_pancake, jam_toast, snack, combo)
            flavor: 口味
            rice: 米種 (飯糰)
            size: 杯型 (飲料)
            temp: 溫度 (飲料)
            quantity: 數量
            large: 是否加大 (飯糰)
            extra_egg: 是否加蛋 (飯糰)

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

            # 根據品項類型填充字段
            if item_type == "riceball":
                if flavor:
                    item["flavor"] = flavor
                if rice:
                    item["rice"] = rice
                item["large"] = bool(large)
                item["extra_egg"] = bool(extra_egg)

            elif item_type == "drink":
                if flavor:
                    item["drink"] = flavor
                if temp:
                    item["temp"] = temp
                if size:
                    item["size"] = size

            elif item_type == "carrier":
                if flavor:
                    item["carrier"] = flavor
                    item["flavor"] = flavor

            elif item_type in ["egg_pancake", "jam_toast"]:
                if flavor:
                    item["flavor"] = flavor
                if size:
                    item["size"] = size

            elif item_type == "snack":
                if flavor:
                    item["snack"] = flavor

            # 添加到購物車
            session["cart"].append(item)

            # 返回確認信息
            return {
                "ok": True,
                "message": f"已添加 {quantity} 份 {flavor or item_type}",
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
            item = {
                "itemtype": item_type,
                "flavor": flavor,
                "rice": rice,
                "size": size,
                "temp": temp,
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

    def checkout(self) -> Dict[str, Any]:
        """
        準備結帳

        Returns:
            結帳摘要
        """
        try:
            session = self.get_current_session()

            if session.get("pending_frames"):
                pending = session["pending_frames"][0]
                return {
                    "ok": False,
                    "message": "還有未補完的品項資訊，請先完成",
                    "pending_item": pending.get("itemtype"),
                }

            if not session["cart"]:
                return {"ok": False, "message": "購物車為空，無法結帳"}

            # 生成結帳摘要
            summary = self.dm.get_order_summary(self._session_id)
            total = self.dm._calculate_cart_total(session)

            # 標記狀態為確認中
            session["status"] = "CONFIRMING_CHECKOUT"

            return {
                "ok": True,
                "message": f"{summary}。確定要送出訂單嗎？",
                "total_price": total,
                "requires_confirmation": True,
            }

        except Exception as e:
            return {"ok": False, "error": str(e)}

    def confirm_order(self, confirmed: bool = True) -> Dict[str, Any]:
        """
        確認並提交訂單

        Args:
            confirmed: 是否確認送出訂單

        Returns:
            提交結果
        """
        try:
            session = self.get_current_session()

            if not confirmed:
                session["status"] = "OPEN"
                return {
                    "ok": True,
                    "message": "已取消訂單提交",
                }

            # 提交訂單
            result_msg = self.dm._submit_order(session)

            return {
                "ok": True,
                "message": result_msg,
                "order_id": session.get("order_payload", {}).get("order_id"),
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
                    "description": "添加品項到購物車",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "item_type": {
                                "type": "string",
                                "description": "品項類型 (riceball, drink, carrier, egg_pancake, jam_toast, snack)",
                            },
                            "flavor": {
                                "type": "string",
                                "description": "品項口味或名稱",
                            },
                            "rice": {
                                "type": "string",
                                "description": "米種 (紫米/白米/混米) - 飯糰用",
                            },
                            "size": {
                                "type": "string",
                                "description": "杯型 (中杯/大杯) - 飲料用",
                            },
                            "temp": {
                                "type": "string",
                                "description": "溫度 (冰的/溫的) - 飲料用",
                            },
                            "quantity": {
                                "type": "integer",
                                "description": "數量",
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
                    "name": "checkout",
                    "description": "準備結帳，生成訂單摘要並等待確認",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "confirm_order",
                    "description": "確認並提交訂單，或取消訂單提交",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "confirmed": {
                                "type": "boolean",
                                "description": "是否確認送出訂單",
                                "default": True,
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
            "add_to_cart": self.add_to_cart,
            "remove_from_cart": self.remove_from_cart,
            "get_cart_summary": self.get_cart_summary,
            "query_menu": self.query_menu,
            "get_price": self.get_price,
            "checkout": self.checkout,
            "confirm_order": self.confirm_order,
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
                "quantity",
                "large",
                "extra_egg",
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
            "checkout": set(),
            "confirm_order": {"confirmed"},
        }
