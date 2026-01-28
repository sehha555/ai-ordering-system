"""System Prompt 管理模組 - 動態生成和管理 LLM 系統提示"""
from typing import Optional, Dict, Any, List
import os
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
                self._base_prompt = f.read()
        except FileNotFoundError:
            raise RuntimeError(f"Base prompt file not found at {prompt_path}")

        return self._base_prompt

    def _generate_menu_summary(self) -> str:
        """從菜單生成摘要"""
        if self._menu_summary is not None:
            return self._menu_summary

        try:
            menu_data = get_raw_menu()
        except RuntimeError as e:
            raise RuntimeError(f"Failed to load menu data: {e}")

        # 按類別組織菜單
        menu_by_category: Dict[str, List[Dict[str, Any]]] = {}
        for item in menu_data:
            category = item.get("category", "其他")
            if category not in menu_by_category:
                menu_by_category[category] = []
            menu_by_category[category].append(item)

        # 生成菜單摘要 - 每個類別列出幾個代表性品項
        summary_lines = ["# 菜單摘要"]
        summary_lines.append("")

        for category, items in menu_by_category.items():
            summary_lines.append(f"## {category}")

            # 按價格分組顯示品項
            price_groups: Dict[int, List[str]] = {}
            for item in items:
                price = item.get("price", 0)
                name = item.get("name", "")
                if price not in price_groups:
                    price_groups[price] = []
                price_groups[price].append(name)

            # 輸出價格層級
            for price in sorted(price_groups.keys()):
                names = price_groups[price]
                if len(names) <= 3:
                    summary_lines.append(f"- ${price}: {', '.join(names)}")
                else:
                    # 太多項目時只顯示前幾個
                    summary_lines.append(f"- ${price}: {', '.join(names[:3])} 等")

            summary_lines.append("")

        self._menu_summary = "\n".join(summary_lines)
        return self._menu_summary

    def _generate_tool_usage_rules(self) -> str:
        """生成工具使用規則區塊"""
        rules = """# 重要輸出規則

**你的回覆必須是純粹的自然語言對話，像真人店員說話一樣。**

禁止事項：
- 絕對不要輸出任何程式碼、JSON、或結構化格式
- 絕對不要輸出類似 `.SizeType:` 或 `{...}` 這樣的內容
- 絕對不要輸出 `<think>` 標籤或思考過程
- 不要解釋你在做什麼，直接回覆客人

正確範例：
- 客人：「我要飯糰」→ 你：「好的，請問要什麼口味的飯糰？」
- 客人：「不要辣」→ 你：「好的，不加辣菜脯。還需要什麼嗎？」
- 客人：「溫的」→ 你：「好的，溫的。大杯還是中杯？」

# 工具使用（系統自動處理，你只需要自然對話）

當你需要執行操作時，系統會自動調用對應的工具：
- 添加品項 → add_to_cart
- 刪除品項 → remove_from_cart
- 結帳 → checkout

你的職責是用自然語言與客人對話，收集必要信息。"""

        return rules

    def _format_session_context(self, session_context: Optional[SessionContext]) -> str:
        """格式化會話上下文信息"""
        if session_context is None:
            return ""

        lines = ["# 當前會話狀態", ""]

        # 購物車狀態
        lines.append(f"## 購物車 ({session_context.cart_count} 項)")
        if session_context.cart_items:
            for item in session_context.cart_items:
                lines.append(f"- {item}")
        else:
            lines.append("- （空）")
        lines.append("")

        # 待補槽信息
        if session_context.pending_count > 0:
            lines.append(f"## 待補槽品項 ({session_context.pending_count} 項)")
            for item in session_context.pending_items:
                lines.append(f"- {item}")
            lines.append("")
        else:
            lines.append("## 待補槽品項")
            lines.append("- （無）")
            lines.append("")

        # 會話狀態
        status_display = {
            "OPEN": "進行中",
            "CHECKOUT": "已結帳",
            "CLOSED": "已關閉"
        }.get(session_context.current_status, session_context.current_status)

        lines.append(f"## 會話狀態: {status_display}")
        lines.append("")

        return "\n".join(lines)

    def build(self, session_context: Optional[SessionContext] = None) -> str:
        """
        構建最終的系統提示

        Args:
            session_context: 可選的會話上下文，用於動態注入購物車和待補槽信息

        Returns:
            完整的系統提示字符串
        """
        # 加載基礎提示
        base = self._load_base_prompt()

        # 生成菜單摘要
        menu = self._generate_menu_summary()

        # 生成工具使用規則
        tools = self._generate_tool_usage_rules()

        # 格式化會話上下文（如果提供）
        session_info = self._format_session_context(session_context)

        # 組合所有部分
        parts = [base, "", menu, "", tools]

        if session_info:
            parts.append("")
            parts.append(session_info)

        return "\n".join(parts)


def build_system_prompt(session_context: Optional[SessionContext] = None) -> str:
    """
    便利函數 - 直接構建系統提示

    Args:
        session_context: 可選的會話上下文

    Returns:
        完整的系統提示字符串
    """
    builder = SystemPromptBuilder()
    return builder.build(session_context)
