"""System Prompt 管理模組 - 動態生成和管理 LLM 系統提示"""
from typing import Optional, Dict, Any, List
import os
import re
from src.dm.session_context import SessionContext
from src.tools.menu.menu_price_service import get_raw_menu


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

        self._base_prompt = content.strip()
        return self._base_prompt

    def _generate_tool_usage_rules(self) -> str:
        """生成工具使用規則（精簡版）"""
        return """# 工具使用

當收集到足夠資訊時，系統會自動調用工具：
- add_to_cart：添加品項（需要 item_type + 對應必填欄位）
- remove_from_cart：刪除品項
- get_cart_summary：查詢購物車
- checkout：結帳

## 必填欄位
- 飯糰(riceball)：flavor + rice（米種）
- 飲料(drink)：flavor + size（杯型）+ temp（溫度）
- 蛋餅(egg_pancake)：flavor
- 載體(carrier)：carrier（吐司/漢堡/饅頭）+ flavor
- 套餐(combo)：combo_name

## 常用別名
- 飯糰：傳統=源味傳統、培根=香燻培根、火腿=風味火腿
- 飲料：豆=有糖豆漿、清=無糖豆漿、奶=純鮮奶茶、大冰豆=大杯冰有糖豆漿
- 蛋餅：蛋餅=原味蛋餅、蔬菜蛋餅=高麗菜蛋餅"""

    def _generate_menu_summary(self) -> str:
        """從菜單生成精簡摘要"""
        if self._menu_summary is not None:
            return self._menu_summary

        try:
            menu_data = get_raw_menu()
        except RuntimeError:
            self._menu_summary = ""
            return self._menu_summary

        # 統計各類別數量
        categories: Dict[str, int] = {}
        for item in menu_data:
            cat = item.get("category", "其他")
            categories[cat] = categories.get(cat, 0) + 1

        lines = ["# 菜單類別"]
        for cat, count in sorted(categories.items()):
            lines.append(f"- {cat}：{count} 項")

        self._menu_summary = "\n".join(lines)
        return self._menu_summary

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

    def build(self, session_context: Optional[SessionContext] = None) -> str:
        """
        構建最終的系統提示

        結構：
        1. 基礎提示（從 prompts/system_prompt.md）
        2. 工具使用規則
        3. 菜單摘要
        4. 當前狀態（動態）
        """
        parts = [
            self._load_base_prompt(),
            "",
            self._generate_tool_usage_rules(),
            "",
            self._generate_menu_summary(),
        ]

        session_info = self._format_session_context(session_context)
        if session_info:
            parts.append("")
            parts.append(session_info)

        return "\n".join(parts)


def build_system_prompt(session_context: Optional[SessionContext] = None) -> str:
    """便利函數 - 直接構建系統提示"""
    builder = SystemPromptBuilder()
    return builder.build(session_context)
