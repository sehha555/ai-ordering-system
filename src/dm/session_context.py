"""會話上下文提取 - 協助 LLM 理解當前訂單狀態"""
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict


@dataclass
class SessionContext:
    """從會話提取的上下文訊息，用於 LLM 分類和澄清"""

    cart_count: int  # 購物車中的品項數
    cart_items: List[str]  # 購物車品項摘要
    has_main_item: bool  # 是否已有主食項目（飯糰等）
    has_drink: bool  # 是否已有飲料
    pending_count: int  # 待補槽的品項數
    pending_items: List[str]  # 待補槽品項摘要
    current_status: str  # 會話狀態

    @classmethod
    def from_session(cls, session: Dict[str, Any]) -> "SessionContext":
        """從會話字典提取上下文"""
        cart = session.get("cart", [])
        pending_frames = session.get("pending_frames", [])
        status = session.get("status", "OPEN")

        # 計算購物車統計
        cart_count = len(cart)
        has_main_item = any(
            item.get("itemtype") in ["riceball", "egg_pancake", "carrier", "combo", "snack", "jam_toast"]
            for item in cart
        )
        has_drink = any(item.get("itemtype") == "drink" for item in cart)

        # 提取購物車品項摘要
        cart_items = []
        for item in cart:
            itemtype = item.get("itemtype", "unknown")
            if itemtype == "drink":
                drink_name = item.get("drink", "飲料")
                size = item.get("size", "")
                temp = item.get("temp", "")
                cart_items.append(f"{drink_name}({size}{temp})".replace("()", ""))
            elif itemtype == "riceball":
                flavor = item.get("flavor", "飯糰")
                rice = item.get("rice", "")
                cart_items.append(f"{rice}·{flavor}".replace("·", "") if rice else flavor)
            elif itemtype == "combo":
                combo_name = item.get("combo_name", "套餐")
                cart_items.append(combo_name)
            else:
                # 其他品項類型
                itemtype_display = {
                    "egg_pancake": "蛋餅",
                    "carrier": "載體",
                    "jam_toast": "吐司",
                    "snack": "點心"
                }.get(itemtype, itemtype)
                cart_items.append(itemtype_display)

        # 計算待補槽統計
        pending_count = len(pending_frames)
        pending_items = []
        for frame in pending_frames:
            itemtype = frame.get("itemtype", "unknown")
            missing = frame.get("missing_slots", [])
            if missing:
                itemtype_display = {
                    "riceball": "飯糰",
                    "drink": "飲料",
                    "carrier": "載體",
                    "egg_pancake": "蛋餅",
                    "jam_toast": "吐司",
                    "snack": "點心"
                }.get(itemtype, itemtype)
                pending_items.append(f"{itemtype_display}(缺:{','.join(missing)})")

        return cls(
            cart_count=cart_count,
            cart_items=cart_items,
            has_main_item=has_main_item,
            has_drink=has_drink,
            pending_count=pending_count,
            pending_items=pending_items,
            current_status=status
        )

    def to_dict(self) -> Dict[str, Any]:
        """轉換為字典格式"""
        return asdict(self)
