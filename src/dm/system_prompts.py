"""System Prompt 管理模組 - 動態生成和管理 LLM 系統提示"""
from typing import Optional, Dict
import os
import re
from src.dm.session_context import SessionContext
from src.config.settings import settings

# 分類 key → 中文名稱對應表（用於售完資訊注入，僅列具代表性的分類）
_CATEGORY_KEY_TO_LABEL: Dict[str, str] = {
    "carrier_toast": "吐司",
    "carrier_burger": "漢堡",
    "carrier_thick_toast": "厚片吐司",
    "rice_purple": "紫米",
    "rice_white": "白米",
    "scallion_pancake": "蔥抓餅",
}

# 饅頭種類 key → 可選名稱（用於選項限制描述）
_MANTOU_KEY_TO_NAME: Dict[str, str] = {
    "mantou_black_sugar": "黑糖饅頭",
    "mantou_white": "白饅頭",
    "mantou_black_sugar_roll": "黑糖花捲",
    "mantou_white_roll": "白花捲",
    "mantou_taro": "芋頭饅頭",
}


def _format_rice_restriction(rice_status: dict) -> str:
    """
    根據米種可用狀態產生選項限制描述文字。

    rice_status 格式：{"purple": bool, "white": bool, "mixed": bool}
    回傳空字串表示無限制（三種米都可用）。
    """
    purple_ok = rice_status.get("purple", True)
    white_ok = rice_status.get("white", True)
    mixed_ok = rice_status.get("mixed", True)

    # 三種都可用，不需要限制說明
    if purple_ok and white_ok and mixed_ok:
        return ""

    # 收集不可選的米種名稱
    unavailable = []
    if not purple_ok:
        unavailable.append("紫米")
    if not white_ok:
        unavailable.append("白米")
    # mixed_ok 由 purple_ok AND white_ok 決定，紫米或白米缺就會連帶影響混米
    if not mixed_ok and purple_ok and white_ok:
        # 理論上不會到這裡（混米 = 紫米 AND 白米）
        unavailable.append("混米")

    if not unavailable:
        return ""

    # 判斷剩餘可選的米種
    available = []
    if purple_ok:
        available.append("紫米")
    if white_ok:
        available.append("白米")
    if mixed_ok:
        available.append("混米")

    if not available:
        # 三種米全部不可選
        return "飯糰米種：紫米、白米和混米均不可選（米種已全部售完）"

    unavailable_str = "、".join(unavailable)
    # 只有紫米或白米缺時，混米也受影響（混米需要兩種米）
    if not mixed_ok:
        available_str = "、".join(available)
        return f"飯糰米種：{unavailable_str}不可選，混米也不可選（因原料不足），僅{available_str}可用"
    return f"飯糰米種：{unavailable_str}不可選，僅{'、'.join(available)}可用"


def _get_available_mantou(sold_cats: Dict[str, bool]) -> Optional[list]:
    """
    計算目前可用的饅頭種類。

    回傳值：
      None  — 全部 5 種都可選（不需要注入選項限制）
      list  — 部分售完，回傳仍可選的名稱清單
    """
    available = [
        name
        for key, name in _MANTOU_KEY_TO_NAME.items()
        if not sold_cats.get(key, False)
    ]
    # 全部可選時回傳 None，表示不需要限制說明
    if len(available) == len(_MANTOU_KEY_TO_NAME):
        return None
    return available


class SystemPromptBuilder:
    """構建和管理動態系統提示的類"""

    def __init__(self):
        """初始化 SystemPromptBuilder"""
        self._base_prompt: Optional[str] = None
        self._menu_summary: Optional[str] = None

    def _load_base_prompt(self) -> str:
        """從 prompts/system_prompt.md 讀取基礎提示"""
        if self._base_prompt is not None:
            return self._base_prompt

        # 構建提示文件的路徑
        current_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(os.path.dirname(current_dir))
        prompt_path = os.path.join(project_root, "prompts", "system_prompt.md")

        try:
            with open(prompt_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except FileNotFoundError:
            raise RuntimeError(f"Base prompt file not found at {prompt_path}")

        # 移除 "LLM 增強功能" 區塊（舊架構用的）
        content = re.sub(
            r'# LLM 增強功能.*?(?=# Core Rules)',
            '',
            content,
            flags=re.DOTALL
        )

        content = content.replace("{store_name}", settings.STORE_NAME)
        self._base_prompt = content.strip()
        return self._base_prompt

    def _generate_tool_usage_rules(self) -> str:
        """生成工具使用規則（精簡版，與 system_prompt.md 互補不重複）"""
        return """# 常用別名
- 飯糰：傳統=源味傳統、培根=香燻培根、火腿=風味火腿
- 飲料：豆=有糖豆漿、清=無糖豆漿、奶=純鮮奶茶、大冰豆=大杯冰有糖豆漿
- 蛋餅：蛋餅=原味蛋餅、蔬菜蛋餅=高麗菜蛋餅"""

    def _format_session_context(self, session_context: Optional[SessionContext]) -> str:
        """格式化會話上下文信息"""
        if session_context is None:
            return ""

        lines = ["# 當前狀態"]

        # 購物車
        if session_context.cart_items:
            lines.append(f"購物車（{session_context.cart_count} 項）：")
            for item in session_context.cart_items:
                lines.append(f"  - {item}")
        else:
            lines.append("購物車：空")

        # 待補槽
        if session_context.pending_count > 0:
            lines.append(f"待補資訊（{session_context.pending_count} 項）：")
            for item in session_context.pending_items:
                lines.append(f"  - {item}")

        return "\n".join(lines)

    def _format_business_status(self) -> str:
        """
        格式化營業狀態注入文字。

        營業中不注入（預設假設），非營業時間才提示 LLM。
        """
        from src.tools.menu import menu_state_service  # noqa: PLC0415

        is_open = menu_state_service.is_currently_open()
        hours = menu_state_service.get_business_hours()

        if not is_open:
            return f"【營業狀態】目前非營業時間（營業 {hours['open']}-{hours['close']}），請告知客人目前沒有營業。"
        return ""

    def _format_sold_out_info(self) -> str:
        """
        從 menu_state_service 讀取售完狀態，格式化為注入文字。

        使用 lazy import 避免循環依賴。
        只在有售完品項時才產生內容，零售完回傳空字串。
        """
        # lazy import — 避免模組層級循環依賴
        from src.tools.menu import menu_state_service  # noqa: PLC0415

        # 取得有效售完品項（含連動規則展開後的完整清單）
        effective_items = menu_state_service.get_effective_sold_out()
        # 取得分類售完狀態
        sold_cats = menu_state_service.get_sold_out_categories()
        # 取得套餐狀態
        combo_status = menu_state_service.get_effective_combo_status()

        # 判斷哪些分類已售完（有對應中文標籤的才顯示為「售完分類」）
        sold_category_labels = [
            label
            for key, label in _CATEGORY_KEY_TO_LABEL.items()
            if sold_cats.get(key, False)
        ]

        # 判斷不可用套餐
        unavailable_combos = [
            name for name, status in combo_status.items()
            if not status["available"]
        ]

        # 判斷饅頭選項限制（部分饅頭種類售完，尚有剩餘可選者）
        mantou_available = _get_available_mantou(sold_cats)
        mantou_restriction = ""
        if mantou_available is not None:
            # mantou_available 為 None 表示全部可選（無限制）
            if mantou_available:
                mantou_restriction = f"饅頭只剩{'、'.join(mantou_available)}"
            # 空 list 表示所有饅頭都售完，由 effective_items 處理，此處不重複

        # 判斷鐵板麵麵種限制
        noodle_oil_off = sold_cats.get("noodle_oil", False)
        noodle_udon_off = sold_cats.get("noodle_udon", False)
        noodle_restriction = ""
        if noodle_oil_off and not noodle_udon_off:
            noodle_restriction = "鐵板麵只能選烏龍麵"
        elif noodle_udon_off and not noodle_oil_off:
            noodle_restriction = "鐵板麵只能選油麵"
        # 兩種都關的情況由 effective_items 顯示，不另列選項限制

        # 判斷飯糰米種選項限制（米種是點餐選項，不是獨立品項，需要以選項限制格式告知 LLM）
        rice_status = menu_state_service.get_rice_options_status()
        rice_restriction = _format_rice_restriction(rice_status)

        # 收集所有選項限制行
        option_restrictions = [r for r in [mantou_restriction, noodle_restriction, rice_restriction] if r]

        # 完全沒有任何售完資訊 → 回傳空字串（零售完不佔 token）
        if not (effective_items or sold_category_labels or unavailable_combos or option_restrictions):
            return ""

        lines = ["【售完資訊】"]

        if effective_items:
            lines.append(f"售完：{'、'.join(effective_items)}")

        if sold_category_labels:
            lines.append(f"售完分類：{'、'.join(sold_category_labels)}（相關品項不可點）")

        if unavailable_combos:
            lines.append(f"不可用套餐：{'、'.join(unavailable_combos)}")

        if option_restrictions:
            lines.append(f"選項限制：{'；'.join(option_restrictions)}")

        return "\n".join(lines)

    def build(self) -> str:
        """
        構建系統提示（靜態部分確保 prefix cache 命中，動態資訊附加尾段）

        結構：
        1. 基礎提示（從 prompts/system_prompt.md）
        2. 工具使用規則
        3. 菜單摘要
        4. 營業狀態（動態，非營業時間才出現）
        5. 售完資訊（動態，只在有售完時出現）
        — 4+5 放最尾段避免破壞前段 prefix cache
        """
        parts = [
            self._load_base_prompt(),
            "",
            self._generate_tool_usage_rules(),
        ]

        # 動態內容放最尾段（避免插入中間破壞 prefix cache）
        business_status = self._format_business_status()
        if business_status:
            parts.append("")
            parts.append(business_status)

        sold_out_info = self._format_sold_out_info()
        if sold_out_info:
            parts.append("")
            parts.append(sold_out_info)

        return "\n".join(parts)

    def build_context_message(self, session_context: Optional[SessionContext]) -> Optional[str]:
        """
        構建動態上下文訊息（購物車/待補槽），作為獨立 message 注入

        放在 history 之後、user message 之前，避免破壞 prefix cache。
        回傳 None 表示無需注入。
        """
        text = self._format_session_context(session_context)
        return text if text else None


def build_system_prompt() -> str:
    """便利函數 - 構建靜態系統提示"""
    builder = SystemPromptBuilder()
    return builder.build()


def build_context_message(session_context: Optional[SessionContext]) -> Optional[str]:
    """便利函數 - 構建動態上下文訊息"""
    builder = SystemPromptBuilder()
    return builder.build_context_message(session_context)
