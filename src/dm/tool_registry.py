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
from src.config.config_loader import load_json_config

# 各品類工具：resolve + build_cart_item
from src.tools.riceball_tool import (
    resolve_flavor as _riceball_resolve,
    build_cart_item as _build_riceball,
)
from src.tools.drink_tool import (
    resolve_flavor as _drink_resolve,
    is_valid_drink_input as _is_valid_drink_input,
    build_cart_item as _build_drink,
)
from src.tools.egg_pancake_tool import (
    resolve_flavor as _ep_resolve,
    build_cart_item as _build_egg_pancake,
)
from src.tools.snack_tool import (
    resolve_flavor as _snack_resolve,
    build_cart_item as _build_snack,
)
from src.tools.carrier_tool import build_cart_item as _build_carrier
from src.tools.combo_tool import build_cart_item as _build_combo
import asyncio
from datetime import datetime
from src.api.order_broadcaster import order_broadcaster, format_order_for_admin
from src.repository.order_repository import order_repo
from rapidfuzz import fuzz, process
from pypinyin import lazy_pinyin

# 子字串匹配最低長度比例（step 8 fallback）
_SUBSTRING_MATCH_MIN_RATIO = 0.6

# Subsequence 匹配最低長度比例（step 9）— 「煎吐司→煎蛋吐司」等漏字場景
_SUBSEQUENCE_MATCH_MIN_RATIO = 0.6

# Rapidfuzz 模糊匹配 cutoff（step 10）— 最後 fallback，避免誤匹配要嚴格
_FUZZY_MATCH_CUTOFF = 80


def _is_subsequence(short: str, long: str) -> bool:
    """short 的所有字符按順序出現在 long 中（不要求連續）"""
    it = iter(long)
    return all(c in it for c in short)


# 從 aliases_registry.json 載入 4 個常數
_reg_cfg = load_json_config("aliases_registry.json")
# 公開：text_tag_executor 的 slot-strip 需要用別名比對品項是否被 text 點名
COMBO_NUMBER_ALIASES: Dict[str, str] = _reg_cfg["combo_number_aliases"]
_COLLOQUIAL_ALIASES: Dict[str, str] = _reg_cfg["colloquial_aliases"]
_CARRIER_SUFFIXES: List[str] = _reg_cfg["carrier_suffixes"]
_CARRIER_CATEGORY_MAP: Dict[str, str] = _reg_cfg["carrier_category_map"]

# 果醬吐司名稱解析（預編譯，避免 add_item 內部每次 import + compile）
_JAM_TOAST_RE = re.compile(r"果醬吐司\(([^/]+)/([^)]+)\)")

# 鐵板麵別名（口味 + 麵體）— 從 aliases_iron_noodle.json 載入
_iron_noodle_cfg = load_json_config("aliases_iron_noodle.json")
_IRON_NOODLE_FLAVOR_CANON: Dict[str, str] = _iron_noodle_cfg["flavor_aliases"]
_NOODLE_TYPE_CANON: Dict[str, str] = _iron_noodle_cfg["noodle_type_aliases"]
# 排序：長 alias 優先，避免「黑椒」被「黑」截
_IRON_NOODLE_FLAVOR_KEYS = tuple(sorted(_IRON_NOODLE_FLAVOR_CANON.keys(), key=len, reverse=True))


def _resolve_iron_noodle_menu_name(name_input: str, noodle: str) -> Optional[str]:
    """從口味字串 + 麵體組出鐵板麵完整 menu_name，例：「黑椒鐵板麵」+「油麵」→「黑椒鐵板麵(油麵)+蛋」"""
    if not name_input or not noodle:
        return None
    flavor_canon: Optional[str] = None
    for alias in _IRON_NOODLE_FLAVOR_KEYS:
        if alias in name_input:
            flavor_canon = _IRON_NOODLE_FLAVOR_CANON[alias]
            break
    if not flavor_canon:
        return None
    noodle_canon = _NOODLE_TYPE_CANON.get(noodle)
    if not noodle_canon:
        return None
    menu_name = f"{flavor_canon}鐵板麵({noodle_canon})+蛋"
    if menu_name not in _MENU_INDEX:
        return None
    return menu_name


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


def _build_pinyin_index() -> Dict[str, str]:
    """無聲調拼音 → 菜單 base name（去括號規格）。158 品項已驗證零拼音碰撞。"""
    index: Dict[str, str] = {}
    for full_name in _MENU_INDEX:
        base = full_name.split("(")[0]
        index.setdefault("".join(lazy_pinyin(base)), base)
    return index


_PINYIN_INDEX: Dict[str, str] = _build_pinyin_index()


def _augment_with_sold_out_rice(base_msg: str) -> str:
    """米種售完時前綴注入訊息，無售完原樣返回。"""
    rice_status = menu_state_service.get_rice_options_status()
    sold_rices: List[str] = []
    if not rice_status["white"]:
        sold_rices.append("白米")
    if not rice_status["purple"]:
        sold_rices.append("紫米")
    if not sold_rices:
        return base_msg
    return f"{'、'.join(sold_rices)}售完，{base_msg}"


def _sold_out_block(menu_name: str) -> Optional[Dict[str, Any]]:
    """品項命中今日售完清單 → 回傳擋下用的 ok:false dict；未售完回 None。

    售完是後端硬攔截，不依賴 LLM 自律：模型即使輸出 [ADD:售完品項]，
    此處仍會擋下，不讓它進購物車。
    """
    if menu_name and menu_name in menu_state_service.get_effective_sold_out():
        return {"ok": False, "message": f"{menu_name}今天賣完了，要不要換別的？"}
    return None


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
        0. 口語俗稱（「花生厚片」→「果醬吐司(花生/厚片)」）
        1. 精確匹配 _MENU_INDEX（含完整品項名如「有糖豆漿(中)」）
        2. 套餐 startsWith 匹配（「套餐一」→「套餐一 醬燒肉片蛋餅+豆漿(大)」）
        3. 套餐數字別名解析（「三號餐」→「套餐三」）
        3.5 拼音同音匹配（ASR 同音錯字：「委魚飯糰」→「鮪魚飯糰」）
        4. 飲料別名解析後比對（不含杯型，加杯型後再精確匹配）
        5. 飯糰別名解析後比對
        6. 蛋餅別名解析後比對
        7. 點心別名解析後比對
        8. 子字串 / subsequence 匹配（輔助）
        9. Rapidfuzz 模糊匹配（最終 fallback）
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
                return {"category": "套餐", "price": info["price"], "resolved_name": name}

        # 3. 套餐本身就是短名（如「套餐一」精確不中但存在套餐）
        resolved_combo = COMBO_NUMBER_ALIASES.get(name)
        if resolved_combo:
            return self._resolve_item_name(resolved_combo)

        # 3.5 拼音同音匹配（全名同音才命中，精度高於後續子字串式別名解析，
        # 須先攔截避免「企司蛋餅」被蛋餅別名吃成原味蛋餅）
        corrected = _PINYIN_INDEX.get("".join(lazy_pinyin(name)))
        if corrected and corrected != name:
            return self._resolve_item_name(corrected)

        # 4. 飲料別名解析（得到標準名，不含杯型；杯型由 add_item 外層提供）
        resolved_drink = _drink_resolve(name)
        if resolved_drink and resolved_drink != name and _is_valid_drink_input(name):
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
        resolved_riceball = _riceball_resolve(name)
        if resolved_riceball:
            for full_name, info in _MENU_INDEX.items():
                if info["category"] == "飯糰" and full_name.endswith(resolved_riceball):
                    return {
                        "category": "飯糰",
                        "price": info["price"],
                        "resolved_name": resolved_riceball,
                    }
            if resolved_riceball in _MENU_INDEX:
                return {**_MENU_INDEX[resolved_riceball], "resolved_name": resolved_riceball}

        # 6. 蛋餅別名解析
        resolved_ep = _ep_resolve(name)
        if resolved_ep and resolved_ep != name:
            if resolved_ep in _MENU_INDEX:
                return {**_MENU_INDEX[resolved_ep], "resolved_name": resolved_ep}

        # 7. 點心別名解析
        resolved_snack = _snack_resolve(name, _MENU_INDEX)
        if resolved_snack and resolved_snack != name and resolved_snack in _MENU_INDEX:
            return {**_MENU_INDEX[resolved_snack], "resolved_name": resolved_snack}

        # 8. 子字串匹配（雙方都去掉規格括號後比較，要求 >= 60% 長度比例）
        #    輸入側也要去：LLM 會腦補規格（「鮮肉包(8顆)」套煎餃格式），
        #    帶括號直接比長度比例過不了。
        #    命中多個（同 base 多變體，如果醬吐司 10 種口味）不可短路取第一個
        #    —— 用原始 name（括號內是口味/規格資訊）fuzzy 挑最相近的變體
        #    + Subsequence 匹配（漏字場景：「煎吐司」→「煎蛋吐司」）
        #    子字串優先：全 index 掃完無子字串命中，才開始比 subsequence
        name_base = name.split("(")[0].strip() if "(" in name else name
        substr_hits: List[str] = []
        subseq_match: Optional[Dict[str, Any]] = None
        for full_name, info in _MENU_INDEX.items():
            base = full_name.split("(")[0] if "(" in full_name else full_name
            if name_base in base or base in name_base:
                shorter = min(len(name_base), len(base))
                longer = max(len(name_base), len(base))
                if shorter >= longer * _SUBSTRING_MATCH_MIN_RATIO:
                    substr_hits.append(full_name)
            if (
                subseq_match is None
                and len(name_base) >= len(base) * _SUBSEQUENCE_MATCH_MIN_RATIO
                and _is_subsequence(name_base, base)
            ):
                subseq_match = {**info, "resolved_name": full_name}
        if substr_hits:
            if len(substr_hits) == 1:
                matched = substr_hits[0]
            else:
                matched = process.extractOne(name, substr_hits, scorer=fuzz.ratio)[0]
            return {**_MENU_INDEX[matched], "resolved_name": matched}
        if subseq_match:
            return subseq_match

        # 9. Rapidfuzz 模糊匹配（typo / 字面相近場景，cutoff 80% 避免誤匹配）
        choices = list(_MENU_INDEX.keys())
        best = process.extractOne(
            name, choices, scorer=fuzz.ratio, score_cutoff=_FUZZY_MATCH_CUTOFF
        )
        if best:
            matched_name = best[0]
            return {**_MENU_INDEX[matched_name], "resolved_name": matched_name}

        return None

    def add_item(
        self,
        name: str,
        quantity: int = 1,
        rice: Optional[str] = None,
        size: Optional[str] = None,
        temp: Optional[str] = None,
        flavor: Optional[str] = None,
        noodle: Optional[str] = None,
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

        # 鐵板麵 fast-path：有 noodle 參數 + name 含鐵板麵口味關鍵字 → 直接走 resolver。
        if noodle and any(alias in name for alias in _IRON_NOODLE_FLAVOR_KEYS):
            menu_name = _resolve_iron_noodle_menu_name(name, noodle)
            if menu_name:
                blocked = _sold_out_block(menu_name)
                if blocked:
                    return blocked
                return self.add_snack(
                    flavor=menu_name,
                    quantity=quantity,
                    customization=customization,
                )

        # 找到品項資訊
        item_info = self._resolve_item_name(name)
        if item_info is None:
            return {"ok": False, "message": f"找不到「{name}」，請確認名稱或查詢菜單"}

        category = item_info["category"]
        resolved_name = item_info["resolved_name"]

        # ── 售完硬攔截：命中今日售完清單就擋下，不准進購物車 ──
        blocked = _sold_out_block(resolved_name)
        if blocked:
            return blocked

        # ── 飯糰 ──
        if category == "飯糰":
            if not rice:
                return {
                    "ok": False,
                    "missing": ["rice"],
                    "message": _augment_with_sold_out_rice("飯糰要白米紫米還是混米？"),
                }
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
            extracted_flavor = resolved_name
            for suffix in _CARRIER_SUFFIXES:
                if extracted_flavor.endswith(suffix):
                    extracted_flavor = extracted_flavor[: -len(suffix)]
                    break

            # 饅頭特殊處理：若 rice 含口味資訊（非真正米種），重建完整品項名
            _RICE_TYPES = {"白米", "紫米", "混米"}
            if category == "饅頭" and rice and rice not in _RICE_TYPES:
                rebuilt = f"{rice}{resolved_name}"
                rebuilt_info = self._resolve_item_name(rebuilt)
                if rebuilt_info is not None and rebuilt_info.get("category") == "饅頭":
                    return self.add_item(
                        name=rebuilt, quantity=quantity, customization=customization
                    )
                rebuilt_base = f"{rice}饅頭"
                rebuilt_base_info = self._resolve_item_name(rebuilt_base)
                if rebuilt_base_info is not None and rebuilt_base_info.get("category") == "饅頭":
                    return self.add_item(
                        name=rebuilt_base, quantity=quantity, customization=customization
                    )

            return self.add_carrier(
                carrier=carrier,
                flavor=extracted_flavor,
                menu_name=resolved_name,
                quantity=quantity,
                customization=customization,
            )

        # ── 蛋餅 ──
        if category == "蛋餅":
            if name == "蛋餅" and not flavor:
                return {"ok": False, "missing": ["flavor"], "message": "蛋餅要什麼口味？"}
            if name == "蛋餅" and flavor:
                return self.add_item(
                    name=f"{flavor}蛋餅", quantity=quantity, customization=customization
                )
            ep_flavor = resolved_name
            if ep_flavor.endswith("蛋餅"):
                ep_flavor = ep_flavor[:-2]
            return self.add_egg_pancake(
                flavor=ep_flavor, quantity=quantity, customization=customization
            )

        # ── 果醬吐司 ──
        if category == "果醬吐司":
            jam_flavor = flavor
            jam_size = size or "薄片"
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

        # ── 點心 / 蔥抓餅 ──
        if category in ("點心", "蔥抓餅"):
            return self.add_snack(
                flavor=resolved_name, quantity=quantity, customization=customization
            )

        # ── 鐵板麵（必填麵種：油麵/烏龍麵；組成完整 menu_name 為 source of truth）──
        if category == "鐵板麵":
            if not noodle:
                return {
                    "ok": False,
                    "missing": ["noodle"],
                    "message": "油麵還是烏龍麵？",
                }
            menu_name = _resolve_iron_noodle_menu_name(name, noodle)
            if not menu_name:
                return {
                    "ok": False,
                    "message": f"鐵板麵口味或麵種無法辨識：{name} / {noodle}",
                }
            return self.add_snack(
                flavor=menu_name,
                quantity=quantity,
                customization=customization,
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

    # ============ 購物車操作共用 ============

    def _append_to_cart(
        self, item_data: Dict[str, Any], prefix: str, display_name: str
    ) -> Dict[str, Any]:
        """取 session → 分配 item_id → append to cart → 回傳標準成功 dict"""
        try:
            session = self.get_current_session()
            item_id = self._next_item_id(session, prefix)
            item_data["item_id"] = item_id
            session["cart"].append(item_data)
            qty = item_data.get("quantity", 1)
            return {
                "ok": True,
                "item_id": item_id,
                "message": f"已加入 {qty}份 {display_name}",
                "cart_count": len(session["cart"]),
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ============ 品項專屬工具（薄包裝，邏輯在 *_tool.build_cart_item）============

    def add_riceball(
        self,
        flavor=None,
        rice=None,
        large=False,
        extra_egg=False,
        spicy=False,
        quantity=1,
        customization=None,
    ) -> Dict[str, Any]:
        result = _build_riceball(
            flavor=flavor,
            rice=rice,
            large=large,
            extra_egg=extra_egg,
            spicy=spicy,
            quantity=quantity,
            customization=customization,
        )
        return (
            result
            if not result["ok"]
            else self._append_to_cart(result["item"], "riceball", result["display_name"])
        )

    def add_drink(
        self, flavor=None, size=None, temp=None, quantity=1, customization=None
    ) -> Dict[str, Any]:
        result = _build_drink(
            flavor=flavor, size=size, temp=temp, quantity=quantity, customization=customization
        )
        return (
            result
            if not result["ok"]
            else self._append_to_cart(result["item"], "drink", result["display_name"])
        )

    def add_carrier(
        self, carrier=None, flavor=None, menu_name=None, quantity=1, customization=None
    ) -> Dict[str, Any]:
        result = _build_carrier(
            carrier=carrier,
            flavor=flavor,
            menu_name=menu_name,
            quantity=quantity,
            customization=customization,
        )
        return (
            result
            if not result["ok"]
            else self._append_to_cart(result["item"], "carrier", result["display_name"])
        )

    def add_egg_pancake(self, flavor=None, quantity=1, customization=None) -> Dict[str, Any]:
        result = _build_egg_pancake(flavor=flavor, quantity=quantity, customization=customization)
        return (
            result
            if not result["ok"]
            else self._append_to_cart(result["item"], "egg_pancake", result["display_name"])
        )

    def add_snack(self, flavor=None, quantity=1, customization=None) -> Dict[str, Any]:
        resolved = _snack_resolve(flavor, _MENU_INDEX) or flavor
        result = _build_snack(flavor=resolved, quantity=quantity, customization=customization)
        return (
            result
            if not result["ok"]
            else self._append_to_cart(result["item"], "snack", result["display_name"])
        )

    def add_combo(
        self,
        combo_name=None,
        rice=None,
        temp=None,
        flavor=None,
        customization=None,
        quantity=1,
    ) -> Dict[str, Any]:
        result = _build_combo(
            combo_name=combo_name,
            rice=rice,
            temp=temp,
            flavor=flavor,
            customization=customization,
            quantity=quantity,
        )
        if not result["ok"]:
            if "rice" in result.get("missing", []):
                result["message"] = _augment_with_sold_out_rice(result["message"])
            return result
        return self._append_to_cart(result["item"], "combo", result["display_name"])

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

    def set_item_quantity(
        self,
        item_id: str,
        quantity: int,
    ) -> Dict[str, Any]:
        """修改購物車中指定品項的數量，qty=0 等同移除"""
        try:
            session = self.get_current_session()
            cart = session["cart"]
            for i, item in enumerate(cart):
                if item.get("item_id") == item_id:
                    if quantity <= 0:
                        cart.pop(i)
                        return {"ok": True, "message": f"已移除 {cart_manager.format_item(item)}"}
                    old_qty = item.get("quantity", 1)
                    item["quantity"] = quantity
                    return {
                        "ok": True,
                        "message": f"{cart_manager.format_item(item)} 數量 {old_qty} → {quantity}",
                    }
            return {"ok": False, "message": f"找不到 item_id={item_id}"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def set_item_attrs(
        self,
        item_id: str,
        size: Optional[str] = None,
        temp: Optional[str] = None,
    ) -> Dict[str, Any]:
        """修改購物車品項的杯型/溫度（「紅茶換大杯」「豆漿改溫的」）。

        LLM 慣性用 [SET_QTY:品項|size=大杯] 表達屬性修改，此為對應的執行端。
        size 只適用飲品；temp 適用飲品與套餐（套餐附飲料）。價格由
        get_price_info 依欄位重新報價，不需在此處理。
        """
        from src.tools.drink_tool import resolve_size, resolve_temp

        try:
            session = self.get_current_session()
            for item in session["cart"]:
                if item.get("item_id") != item_id:
                    continue
                itemtype = item.get("itemtype")
                changed = []
                if size:
                    if itemtype != "drink":
                        return {"ok": False, "message": "只有飲料可以換杯型喔"}
                    item["size"] = resolve_size(size) or size
                    changed.append(item["size"])
                if temp:
                    if itemtype not in ("drink", "combo"):
                        return {"ok": False, "message": "這個品項沒有溫度選項喔"}
                    item["temp"] = resolve_temp(temp) or temp
                    changed.append(item["temp"])
                if not changed:
                    return {"ok": False, "message": "沒有可修改的選項"}
                core = item.get("drink") or item.get("combo_name") or "品項"
                return {
                    "ok": True,
                    "message": f"已把{core}換成{'、'.join(changed)}",
                }
            return {"ok": False, "message": f"找不到 item_id={item_id}"}
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
                recipes_path = (
                    Path(__file__).resolve().parent.parent
                    / "tools"
                    / "menu"
                    / "riceball_recipes.json"
                )
                try:
                    with open(recipes_path, encoding="utf-8") as _f:
                        result["recipes"] = json.load(_f)
                except Exception:
                    pass

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
                if not pi or not pi.get("ok"):
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

            # 客製待確認：有 pending 品項 → 不能先付，標未付待店員結算
            has_pending = cart_manager.cart_has_pending(cart)
            payment_status = "UNPAID" if has_pending else "PAID"

            # 建立訂單 payload（order_number 由 save_order_with_number 原子性取號）
            order_id = f"order-{self._session_id}-{datetime.now().timestamp()}"

            # 構建品項清單（給前端用）
            items_payload = []
            for item in cart:
                qty = int(item.get("quantity", 1) or 1)
                pi = cart_manager.get_price_info(item)
                item_total = cart_manager.extract_total(pi)
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
                "payment_status": payment_status,
                "price_pending": has_pending,
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
                "payment_status": payment_status,
                "price_pending": has_pending,
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
        """取得工具名到函數的映射"""
        return {
            "add_item": self.add_item,
            "remove_from_cart": self.remove_from_cart,
            "get_cart_summary": self.get_cart_summary,
            "query_menu": self.query_menu,
            "finalize_order": self.finalize_order,
            "preview_checkout": self.preview_checkout,
        }

    def get_allowed_args(self) -> Dict[str, Set[str]]:
        """取得每個工具允許的參數集合"""
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
