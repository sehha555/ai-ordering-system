"""LLM 驅動的澄清問題生成 - 生成自然的補槽問題"""
import logging
from typing import Dict, Any, List, Optional
from src.services.llm_tool_caller import LLMToolCaller
from src.dm.session_context import SessionContext

logger = logging.getLogger(__name__)


class LLMClarifier:
    """使用 LLM 生成上下文感知的澄清問題"""

    def __init__(self, llm: LLMToolCaller):
        self.llm = llm
        # 硬編碼的備選問題（如 LLM 失敗時使用）
        self._hardcoded_questions = {
            "riceball": {
                "flavor": "想要哪個口味的飯糰？",
                "rice": "還差米種，你要紫米、白米還是混米？",
            },
            "drink": {
                "drink": "請問要什麼飲料？",
                "temp": "你要冰的、溫的？",
                "size": "大杯還中杯？",
            },
            "carrier": {
                "carrier": "你要漢堡、吐司還是饅頭？",
                "flavor": "請問要什麼口味？",
            },
            "egg_pancake": {
                "flavor": "請問要什麼口味的蛋餅？",
            },
            "jam_toast": {
                "flavor": "請問要什麼口味的果醬吐司？",
                "size": "要厚片還是薄片呢？",
            },
            "snack": {
                "snack": "請問要什麼點心？",
            },
        }
        self._cache: Dict[str, str] = {}

    def generate_question(
        self,
        itemtype: str,
        missing_slots: List[str],
        pending_frame: Optional[Dict[str, Any]] = None,
        session_context: Optional[SessionContext] = None,
    ) -> str:
        """
        生成自然的澄清問題。

        Args:
            itemtype: 品項類型 (riceball, drink, etc.)
            missing_slots: 缺失的槽位列表
            pending_frame: 當前待補槽的框架
            session_context: 會話上下文（可選）

        Returns:
            自然語言的澄清問題
        """
        if not missing_slots:
            return "請問還需要什麼嗎？"

        # 使用第一個缺失槽位
        slot = missing_slots[0]

        # 檢查快取
        cache_key = f"{itemtype}|{slot}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        try:
            # 嘗試使用 LLM 生成問題
            question = self._generate_with_llm(itemtype, slot, pending_frame, session_context)
        except Exception as e:
            logger.warning(f"LLM question generation failed for {itemtype}.{slot}: {e}")
            # 備選至硬編碼問題
            question = self._get_hardcoded_question(itemtype, slot)

        # 快取結果
        self._cache[cache_key] = question
        return question

    def _generate_with_llm(
        self,
        itemtype: str,
        slot: str,
        pending_frame: Optional[Dict[str, Any]],
        session_context: Optional[SessionContext],
    ) -> str:
        """使用 LLM 生成澄清問題"""

        # 構建上下文信息
        context_str = ""
        if session_context:
            context_str = self._build_context_str(session_context)

        # 構建用戶消息
        frame_info = ""
        if pending_frame:
            # 提取已有的信息
            filled_slots = []
            for key, value in pending_frame.items():
                if value and not key.startswith("_"):
                    filled_slots.append(f"{key}={value}")
            if filled_slots:
                frame_info = f"已有信息: {', '.join(filled_slots)}"

        user_message = f"""你是點餐系統的澄清助手。根據以下信息生成一個自然的澄清問題。

品項類型: {itemtype}
缺失信息: {slot}
{frame_info}
{context_str}

要求:
- 用自然、簡潔的台灣口語
- 只問當前缺失的信息，一次一個
- 不要重複提問已知信息
- 回覆要像真人店員說話

生成一個澄清問題 (只回傳問題本身，不要添加任何額外說明):"""

        messages = [{"role": "user", "content": user_message}]

        # 調用 LLM
        response = self.llm.call_llm(
            messages=messages,
            temperature=0.7,  # 稍高一點以增加自然性
        )

        # 提取問題
        try:
            question = response["choices"][0]["message"].get("content", "").strip()
            if question:
                return question
        except (KeyError, IndexError, AttributeError):
            pass

        # 如果無法提取，備選至硬編碼
        return self._get_hardcoded_question(itemtype, slot)

    def _get_hardcoded_question(self, itemtype: str, slot: str) -> str:
        """獲取硬編碼的備選問題"""
        questions = self._hardcoded_questions.get(itemtype, {})
        return questions.get(slot, "請問要補充什麼？")

    def _build_context_str(self, context: SessionContext) -> str:
        """從上下文構建提示字符串"""
        parts = []

        if context.cart_items:
            parts.append(f"已點: {', '.join(context.cart_items)}")

        if context.pending_items:
            parts.append(f"待補: {', '.join(context.pending_items)}")

        return f"會話上下文: {' | '.join(parts)}" if parts else ""

    def clear_cache(self):
        """清除快取"""
        self._cache.clear()
