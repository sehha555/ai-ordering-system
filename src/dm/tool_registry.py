"""工具註冊表 - 管理 LLM 可調用的工具"""

import contextvars
import json
import re
from pathlib import Path
from typing import Dict, Any, List, Callable, Optional, Set

# per-request session ID（避免全域單例的併發覆蓋問題）
_current_session_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "_current_session_id", default=None
)
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
    SUGAR_MAP as _DRINK_SUGAR_MAP,
    TEMP_SIZE_SHORTCUTS as _DRINK_TEMP_SIZE_SHORTCUTS,
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

# 飲料已知前綴（用於 _is_valid_drink_input 驗證，長字優先，從 drink_tool 來源組合）
_DRINK_MODIFIER_PREFIXES = tuple(
    sorted(
        set(
            list(_DRINK_TEMP_SIZE_SHORTCUTS.keys())
            + list(DRINK_SIZE_MAP.keys())
            + list(DRINK_TEMP_MAP.keys())
            + list(_DRINK_SUGAR_MAP.keys())
        ),
        key=len,
        reverse=True,
    )
)

# 子字串匹配最低長度比例（step 8 fallback）
_SUBSTRING_MATCH_MIN_RATIO = 0.6

# 預排序別名 keys（避免每次 _resolve_alias 重新排序）
_RICEBALL_ALIASES_SORTED = tuple(sorted(RICEBALL_ALIASES.keys(), key=len, reverse=True))
_DRINK_ALIASES_SORTED = tuple(sorted(DRINK_ALIASES.keys(), key=len, reverse=True))
_EGG_PANCAKE_ALIASES_SORTED = tuple(sorted(EGG_PANCAKE_ALIASES.keys(), key=len, reverse=True))
_SNACK_ALIASES_SORTED = tuple(sorted(SNACK_ALIASES.keys(), key=len, reverse=True))

# 載體後綴（用於從完整品項名稱中提取口味）
_CARRIER_SUFFIXES = ["蛋吐司", "吐司", "蛋漢堡", "蛋堡", "漢堡", "蛋饅頭", "饅頭"]

# 載體分類到 carrier 參數的對應
_CARRIER_CATEGORY_MAP = {"吐司": "吐司", "漢堡": "漢堡", "饅頭": "饅頭"}

# 套餐簡稱別名（「一號餐」→「套餐一」等，在別名解析中使用）
_COMBO_NUMBER_ALIASES: Dict[str, str] = {
    "一號餐": "套餐一",
    "二號餐": "套餐二",
    "三號餐": "套餐三",
    "四號餐": "套餐四",
    "五號餐": "套餐五",
    "六號餐": "套餐六",
    "七號餐": "套餐七",
    "A餐": "套餐A",
    "B餐": "套餐B",
    "C餐": "套餐C",
    "D餐": "套餐D",
    "E餐": "套餐E",
}

# 口語俗稱 → 菜單品項名（_resolve_item_name 最先查）
_COLLOQUIAL_ALIASES: Dict[str, str] = {
    "花生厚片": "果醬吐司(花生/厚片)",
    "草莓厚片": "果醬吐司(草莓/厚片)",
    "蒜香厚片": "果醬吐司(蒜香/厚片)",
    "奶酥厚片": "果醬吐司(奶酥/厚片)",
    "巧克力厚片": "果醬吐司(巧克力/厚片)",
}

# 果醬吐司名稱解析（預編譯，避免 add_item 內部每次 import + compile）
_JAM_TOAST_RE = re.compile(r"果醬吐司\(([^/]+)/([^)]+)\)")


def _build_menu_index() -> Dict[str, Dict[str, Any]]:
    """
    啟動時從 menu_all.json 建立 name→{category, price} 索引。
    模組層級呼叫，結果快取為 _MENU_INDEX 供 add_item 使用。
    """
    menu_path = Path(__file__).parent.parent / "tools" / "menu" / "menu_all.json"
    with open(menu_path, encoding="utf-8-sig") as f:
        items = json.load(f)
    index: Dict[str, Dict[str, Any]] = {}
    for item in items:
        name = item.get("name", "")
        if name:
            index[name] = {"category": item.get("category", ""), "price": item.get("price", 0)}
    return index


# 模組載入時建立一次索引（避免每次 add_item 讀檔）
_MENU_INDEX: Dict[str, Dict[str, Any]] = _build_menu_index()

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

    def set_session_id(self, session_id: str) -> None:
        """設置當前會話 ID（per-request，使用 contextvars 避免併發覆蓋）"""
        _current_session_id.set(session_id)

    @property
    def _session_id(self) -> Optional[str]:
        """向後相容：讀取 contextvars 中的 session_id"""
        return _current_session_id.get()

    def get_current_session(self) -> Dict[str, Any]:
        """取得當前會話"""
        sid = _current_session_id.get()
        if not sid:
            raise RuntimeError("Session ID not set")
        return self.store.get(sid)

    # ============ 別名解析輔助方法 ============

    def _resolve_alias(
        self, value: Optional[str], aliases: dict, sorted_keys: Optional[tuple] = None
    ) -> Optional[str]:
        """通用別名解析：在 aliases 中找匹配項，回傳標準名稱；無匹配則原樣回傳。
        sorted_keys: 預排序的 keys tuple（模組層級快取），省去每次排序開銷。
        """
        if value is None:
            return None
        candidates = sorted_keys if sorted_keys is not None else aliases.keys()
        for alias in candidates:
            if alias == value or alias in value:
                return aliases[alias]
        return value

    def _resolve_riceball_flavor(self, flavor: Optional[str]) -> Optional[str]:
        """將飯糰口味別名轉換為標準名稱"""
        return self._resolve_alias(flavor, RICEBALL_ALIASES, _RICEBALL_ALIASES_SORTED)

    def _resolve_drink_flavor(self, flavor: Optional[str]) -> Optional[str]:
        """將飲料別名轉換為標準名稱"""
        return self._resolve_alias(flavor, DRINK_ALIASES, _DRINK_ALIASES_SORTED)

    def _resolve_drink_size(self, size: Optional[str]) -> Optional[str]:
        """將飲料杯型轉換為標準名稱"""
        return self._resolve_alias(size, DRINK_SIZE_MAP)

    def _resolve_drink_temp(self, temp: Optional[str]) -> Optional[str]:
        """將飲料溫度轉換為標準名稱"""
        return self._resolve_alias(temp, DRINK_TEMP_MAP)

    def _resolve_egg_pancake_flavor(self, flavor: Optional[str]) -> Optional[str]:
        """將蛋餅口味別名轉換為標準名稱"""
        return self._resolve_alias(flavor, EGG_PANCAKE_ALIASES, _EGG_PANCAKE_ALIASES_SORTED)

    @staticmethod
    def _is_valid_drink_input(name: str) -> bool:
        """驗證 name 是合法的飲料輸入，避免「珍珠奶茶」透過子字串「奶茶」誤匹配。
        規則：name 本身是 DRINK_ALIASES key，或去掉已知 temp/size 前綴後是 key。
        """
        if name in DRINK_ALIASES:
            return True
        for prefix in _DRINK_MODIFIER_PREFIXES:
            if name.startswith(prefix):
                remainder = name[len(prefix) :]
                if remainder and remainder in DRINK_ALIASES:
                    return True
        return False

    def _resolve_snack_flavor(self, flavor: Optional[str]) -> Optional[str]:
        """將點心別名轉換為標準名稱（已是完整菜單名則跳過，避免子串誤匹配）
        只做完全匹配或 name 結尾是 ≥2 字元的 alias，
        避免 "起司蛋" 因含單字 "蛋" 被錯誤解析為 "荷包蛋"。
        """
        if not flavor:
            return None
        if flavor in _MENU_INDEX:
            return flavor
        for alias in _SNACK_ALIASES_SORTED:
            if alias == flavor:
                return SNACK_ALIASES[alias]
            if len(alias) >= 2 and flavor.endswith(alias):
                return SNACK_ALIASES[alias]
        return None

    def _next_item_id(self, session: Dict[str, Any], prefix: str) -> str:
        """分配下一個 item_id，同時遞增計數器"""
        counter = session.get("cart_id_counter", 0) + 1
        session["cart_id_counter"] = counter
        return f"{prefix}_{counter}"

    # ============ 統一點餐入口 ============

    def _resolve_item_name(self, name: str) -> Optional[Dict[str, Any]]:
        """
        從 name 字串找到對應的菜單品項資訊。
        查詢順序：
        1. 精確匹配 _MENU_INDEX（含完整品項名如「有糖豆漿(中)」）
        2. 套餐 startsWith 匹配（「套餐一」→「套餐一 醬燒肉片蛋餅+豆漿(大)」）
        3. 飲料別名解析後比對（不含杯型，加杯型後再精確匹配）
        4. 飯糰別名解析後比對
        5. 蛋餅別名解析後比對
        6. 點心別名解析後比對
        7. 套餐數字別名解析（「三號餐」→「套餐三」）
        8. 子字串匹配（輔助）
        回傳 None 表示找不到。
        """
        if not name:
            return None

        # 0. 口語俗稱（花生厚片→果醬吐司(花生/厚片) 等）
        if name in _COLLOQUIAL_ALIASES:
            return self._resolve_item_name(_COLLOQUIAL_ALIASES[name])

        # 1. 精確匹配
        if name in _MENU_INDEX:
            return {**_MENU_INDEX[name], "resolved_name": name}

        # 2. 套餐 startsWith 匹配（「套餐一」→ 找 key 以「套餐一 」開頭的）
        for full_name, info in _MENU_INDEX.items():
            if info["category"] == "套餐" and full_name.startswith(name + " "):
                # 回傳時提取短名（「套餐一」），方便後續 add_combo 使用
                return {"category": "套餐", "price": info["price"], "resolved_name": name}

        # 3. 套餐本身就是短名（如「套餐一」精確不中但存在套餐）
        # 注意：套餐別名解析放在這裡一起處理
        resolved_combo = _COMBO_NUMBER_ALIASES.get(name)
        if resolved_combo:
            # 遞迴查找標準套餐名
            return self._resolve_item_name(resolved_combo)

        # 4. 飲料別名解析（得到標準名，不含杯型；杯型由 add_item 外層提供）
        # 驗證：name 必須是已知別名或 [temp/size 前綴]+別名，避免「珍珠奶茶」誤匹配
        resolved_drink = self._resolve_drink_flavor(name)
        if resolved_drink and resolved_drink != name and self._is_valid_drink_input(name):
            probe = f"{resolved_drink}(中)"
            if probe in _MENU_INDEX:
                return {
                    "category": "飲品",
                    "price": _MENU_INDEX[probe]["price"],
                    "resolved_name": resolved_drink,
                }

        # 嘗試直接用 name 作為飲料標準名
        probe_mid = f"{name}(中)"
        if probe_mid in _MENU_INDEX:
            return {
                "category": "飲品",
                "price": _MENU_INDEX[probe_mid]["price"],
                "resolved_name": name,
            }

        # 5. 飯糰別名解析
        resolved_riceball = self._resolve_riceball_flavor(name)
        if resolved_riceball:
            # 在 menu 中找到以 resolved_riceball 結尾的飯糰品項
            for full_name, info in _MENU_INDEX.items():
                if info["category"] == "飯糰" and full_name.endswith(resolved_riceball):
                    return {
                        "category": "飯糰",
                        "price": info["price"],
                        "resolved_name": resolved_riceball,
                    }
            # 若 resolved_riceball 本身就是完整菜單名
            if resolved_riceball in _MENU_INDEX:
                return {**_MENU_INDEX[resolved_riceball], "resolved_name": resolved_riceball}

        # 6. 蛋餅別名解析
        resolved_ep = self._resolve_egg_pancake_flavor(name)
        if resolved_ep and resolved_ep != name:
            if resolved_ep in _MENU_INDEX:
                return {**_MENU_INDEX[resolved_ep], "resolved_name": resolved_ep}

        # 7. 點心別名解析
        resolved_snack = self._resolve_snack_flavor(name)
        if resolved_snack and resolved_snack != name and resolved_snack in _MENU_INDEX:
            return {**_MENU_INDEX[resolved_snack], "resolved_name": resolved_snack}

        # 8. 子字串匹配（去掉規格括號後比較，要求 ≥ 60% 長度比例）
        for full_name, info in _MENU_INDEX.items():
            base = full_name.split("(")[0] if "(" in full_name else full_name
            if name in base or base in name:
                shorter = min(len(name), len(base))
                longer = max(len(name), len(base))
                if shorter >= longer * _SUBSTRING_MATCH_MIN_RATIO:
                    return {**info, "resolved_name": full_name}

        return None

    def add_item(
        self,
        name: str,
        quantity: int = 1,
        rice: Optional[str] = None,
        size: Optional[str] = None,
        temp: Optional[str] = None,
        flavor: Optional[str] = None,
        spicy: bool = False,
        extra_egg: bool = False,
        customization: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        統一點餐入口。LLM 只需傳 name（品項名稱），後端自動路由到正確分類。

        路由規則：
        - 飯糰 → add_riceball（需要 rice，缺則 ok:false 追問）
        - 飲品 → add_drink（需要 size + temp，缺則 ok:false 追問）
        - 吐司/漢堡/饅頭 → add_carrier（自動提取 carrier 和 flavor）
        - 蛋餅 → add_egg_pancake（自動提取 flavor）
        - 果醬吐司 → 解析 flavor/size 後加入
        - 點心/蔥抓餅/鐵板麵 → add_snack
        - 套餐 → add_combo（需要 temp，缺則 ok:false 追問）
        """
        if not name:
            return {"ok": False, "message": "請告訴我要點什麼品項"}

        # 找到品項資訊
        item_info = self._resolve_item_name(name)
        if item_info is None:
            return {"ok": False, "message": f"找不到「{name}」，請確認名稱或查詢菜單"}

        category = item_info["category"]
        resolved_name = item_info["resolved_name"]

        # ── 飯糰 ──
        if category == "飯糰":
            if not rice:
                return {"ok": False, "missing": ["rice"], "message": "飯糰要白米紫米還是混米？"}
            return self.add_riceball(
                flavor=resolved_name,
                rice=rice,
                spicy=spicy,
                extra_egg=extra_egg,
                quantity=quantity,
                customization=customization,
            )

        # ── 飲品（先問溫度，答了再問杯型）──
        if category == "飲品":
            if not temp:
                return {"ok": False, "missing": ["temp"], "message": "冰的還是溫的？"}
            if not size:
                return {"ok": False, "missing": ["size"], "message": "要中杯還是大杯？"}
            return self.add_drink(
                flavor=resolved_name,
                size=size,
                temp=temp,
                quantity=quantity,
                customization=customization,
            )

        # ── 吐司 / 漢堡 / 饅頭（載體） ──
        if category in _CARRIER_CATEGORY_MAP:
            carrier = _CARRIER_CATEGORY_MAP[category]
            # 從完整品項名稱提取口味（去掉載體後綴）
            extracted_flavor = resolved_name
            for suffix in _CARRIER_SUFFIXES:
                if extracted_flavor.endswith(suffix):
                    extracted_flavor = extracted_flavor[: -len(suffix)]
                    break

            # 饅頭特殊處理：若 rice 含口味資訊（非真正米種），重建完整品項名
            # 場景：model 輸出 [ADD:饅頭夾蛋|rice=黑糖]，期望解析為「黑糖饅頭夾蛋」或「黑糖饅頭」
            _RICE_TYPES = {"白米", "紫米", "混米"}
            if category == "饅頭" and rice and rice not in _RICE_TYPES:
                # 先試 {rice}{原始名稱}（如 黑糖饅頭夾蛋）— 只接受饅頭類 category
                rebuilt = f"{rice}{resolved_name}"
                rebuilt_info = self._resolve_item_name(rebuilt)
                if rebuilt_info is not None and rebuilt_info.get("category") == "饅頭":
                    return self.add_item(
                        name=rebuilt, quantity=quantity, customization=customization
                    )
                # 再試 {rice}饅頭（如 黑糖饅頭）
                rebuilt_base = f"{rice}饅頭"
                rebuilt_base_info = self._resolve_item_name(rebuilt_base)
                if rebuilt_base_info is not None and rebuilt_base_info.get("category") == "饅頭":
                    return self.add_item(
                        name=rebuilt_base, quantity=quantity, customization=customization
                    )

            return self.add_carrier(
                carrier=carrier,
                flavor=extracted_flavor,
                quantity=quantity,
                customization=customization,
            )

        # ── 蛋餅 ──
        if category == "蛋餅":
            # 若只傳入分類名（"蛋餅"）且沒有 flavor 參數，追問口味
            if name == "蛋餅" and not flavor:
                return {"ok": False, "missing": ["flavor"], "message": "蛋餅要什麼口味？"}
            # 有 flavor 參數時直接使用（如 add_item(name='蛋餅', flavor='玉米')）
            if name == "蛋餅" and flavor:
                return self.add_item(
                    name=f"{flavor}蛋餅", quantity=quantity, customization=customization
                )
            # 去掉「蛋餅」後綴取得口味
            ep_flavor = resolved_name
            if ep_flavor.endswith("蛋餅"):
                ep_flavor = ep_flavor[:-2]
            return self.add_egg_pancake(
                flavor=ep_flavor, quantity=quantity, customization=customization
            )

        # ── 果醬吐司 ──
        if category == "果醬吐司":
            # resolved_name 格式：「果醬吐司(草莓/薄片)」或傳入的 name 帶括號
            jam_flavor = flavor
            jam_size = size or "薄片"  # 預設薄片
            m = _JAM_TOAST_RE.search(resolved_name)
            if m:
                jam_flavor = m.group(1)
                jam_size = m.group(2)
            if not jam_flavor:
                return {
                    "ok": False,
                    "missing": ["flavor"],
                    "message": "果醬吐司什麼口味？草莓花生蒜香奶酥巧克力",
                }
            session = self.get_current_session()
            item_id = self._next_item_id(session, "jam_toast")
            jam_name = f"果醬吐司({jam_flavor}/{jam_size})"
            item: Dict[str, Any] = {
                "item_id": item_id,
                "itemtype": "jam_toast",
                "flavor": jam_flavor,
                "size": jam_size,
                "jam_toast": jam_name,
                "quantity": max(1, quantity),
            }
            if customization:
                item["customization"] = customization
            session["cart"].append(item)
            return {
                "ok": True,
                "item_id": item_id,
                "message": f"已加入 {quantity}份 {jam_name}",
                "cart_count": len(session["cart"]),
            }

        # ── 點心 / 蔥抓餅 / 鐵板麵 ──
        if category in ("點心", "蔥抓餅", "鐵板麵"):
            return self.add_snack(
                flavor=resolved_name, quantity=quantity, customization=customization
            )

        # ── 套餐 ──
        if category == "套餐":
            return self.add_combo(
                combo_name=resolved_name,
                temp=temp,
                rice=rice,
                flavor=flavor,
                quantity=quantity,
                customization=customization,
            )

        # 未知分類 — 回傳錯誤
        return {"ok": False, "message": f"品項「{name}」分類（{category}）不支援，請查詢菜單"}

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

    # ============ 共用工具 ============

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
                    "item_id": entry["item_id"],
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
        取得 OpenAI Function Calling 格式的工具 schema。

        只暴露 2 個 tool：
        - add_item：統一點餐入口，後端依 name 自動路由
        - query_menu：菜單查詢

        其餘工具（remove_from_cart 等）由 voice_router 直接呼叫，不暴露給 LLM。
        """
        return [
            {
                "type": "function",
                "function": {
                    "name": "add_item",
                    "description": (
                        "加入品項到購物車。所有點餐請求必須透過此工具，禁止跳過直接回覆。"
                        "name 填菜單品項名稱"
                        "（如「香燻培根飯糰」「原味蛋餅」「培根蛋吐司」「純鮮奶茶」「套餐一」「薯餅(1片)」）。"
                        "不確定品項名稱也要呼叫，後端會自動比對。"
                        "飯糰額外必填 rice；飲料額外必填 size 和 temp；套餐額外必填 temp。"
                        "缺少必填欄位時回傳 ok:false 和追問訊息。"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "菜單品項名稱，如「香燻培根飯糰」「純鮮奶茶」「套餐一」「培根蛋吐司」",
                            },
                            "quantity": {
                                "type": "integer",
                                "default": 1,
                                "description": "數量",
                            },
                            "rice": {
                                "type": "string",
                                "enum": ["白米", "紫米", "混米"],
                                "description": "米種（飯糰及含飯糰套餐必填）",
                            },
                            "size": {
                                "type": "string",
                                "enum": ["中杯", "大杯"],
                                "description": "杯型（飲料必填）",
                            },
                            "temp": {
                                "type": "string",
                                "enum": ["冰", "溫", "熱"],
                                "description": "溫度（飲料和套餐飲料必填）",
                            },
                            "flavor": {
                                "type": "string",
                                "description": "子選項（套餐的饅頭口味/鐵板麵口味/吐司口味/果醬口味）",
                            },
                            "spicy": {
                                "type": "boolean",
                                "default": False,
                                "description": "加辣菜脯（飯糰）",
                            },
                            "extra_egg": {
                                "type": "boolean",
                                "default": False,
                                "description": "加蛋（飯糰）",
                            },
                            "customization": {
                                "type": "string",
                                "description": "客製化備註（如「不要小黃瓜」「不要沙拉醬」）",
                            },
                        },
                        "required": ["name"],
                    },
                },
            },
            # remove_from_cart / finalize_order 等由 voice_router 直接呼叫，不暴露給 LLM
            {
                "type": "function",
                "function": {
                    "name": "query_menu",
                    "description": "當客人問有什麼可以點、詢問菜單內容時必須調用，禁止靠記憶直接回覆菜單。回傳分類清單或指定分類的品項（含售罄狀態與價格）；飯糰分類額外附成分表。category 不填則回傳所有分類名稱。",
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
            "add_item": self.add_item,
            "remove_from_cart": self.remove_from_cart,
            "get_cart_summary": self.get_cart_summary,
            "query_menu": self.query_menu,
            "finalize_order": self.finalize_order,
            "preview_checkout": self.preview_checkout,
        }

    def get_allowed_args(self) -> Dict[str, Set[str]]:
        """
        取得每個工具允許的參數集合

        Returns:
            參數映射字典
        """
        return {
            "add_item": {
                "name",
                "quantity",
                "rice",
                "size",
                "temp",
                "flavor",
                "spicy",
                "extra_egg",
                "customization",
            },
            "remove_from_cart": {"index", "item_id", "last", "all"},
            "get_cart_summary": set(),
            "query_menu": {"category"},
            "finalize_order": {"dine_type", "payment_method"},
            "preview_checkout": {"dine_type", "payment_method"},
        }
