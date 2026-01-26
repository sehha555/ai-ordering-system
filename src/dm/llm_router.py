"""LLM 驅動的訂單路由器 - 用於處理關鍵詞路由無法識別的項目"""
import json
import logging
from typing import Dict, Any, Optional
from src.services.llm_tool_caller import LLMToolCaller
from src.dm.session_context import SessionContext

logger = logging.getLogger(__name__)


class LLMRouter:
    """使用 LLM 分類未知訂單項目"""

    def __init__(self, llm: LLMToolCaller, timeout: int = 5, confidence_threshold: float = 0.75):
        self.llm = llm
        self.timeout = timeout  # 秒數
        self.confidence_threshold = confidence_threshold
        self._cache: Dict[str, Dict[str, Any]] = {}  # 簡單快取

    def classify(
        self,
        text: str,
        current_order_has_main: bool = False,
        session_context: Optional[SessionContext] = None,
    ) -> Dict[str, Any]:
        """
        分類用戶文本，確定最可能的路由類型。

        Args:
            text: 用戶輸入的文本
            current_order_has_main: 當前訂單是否有主食
            session_context: 會話上下文（用於更好的分類）

        Returns:
            {
                "route_type": str,  # riceball, drink, carrier, etc. 或 "unknown"
                "confidence": float,  # 0-1 之間的信心度
                "reasoning": str,  # 分類理由
                "alternatives": List[str],  # 備選路由
                "trace": Dict,  # 調試信息
            }
        """
        # 檢查快取
        cache_key = f"{text}|{current_order_has_main}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        try:
            result = self._classify_with_timeout(text, current_order_has_main, session_context)
        except Exception as e:
            logger.error(f"LLM classification failed for '{text}': {e}")
            result = {
                "route_type": "unknown",
                "confidence": 0.0,
                "reasoning": f"LLM 調用失敗: {str(e)}",
                "alternatives": [],
                "trace": {"error": str(e), "fallback": True},
            }

        # 快取結果
        self._cache[cache_key] = result
        return result

    def _classify_with_timeout(
        self,
        text: str,
        current_order_has_main: bool,
        session_context: Optional[SessionContext],
    ) -> Dict[str, Any]:
        """內部分類方法，包括超時處理"""

        # 構建上下文訊息
        context_str = ""
        if session_context:
            context_str = self._build_context_str(session_context)

        # 構建系統提示詞
        system_prompt = self._build_system_prompt(current_order_has_main)

        # 構建用戶消息
        user_message = f"""用戶說: "{text}"

{context_str}

請分類這句話。可能的路由類型有:
- riceball (飯糰)
- egg_pancake (蛋餅)
- carrier (漢堡/吐司/饅頭)
- drink (飲料)
- snack (點心)
- jam_toast (果醬吐司)
- unknown (不確定)

請以 JSON 回應:
{{
    "route_type": "...",
    "confidence": 0.0-1.0,
    "reasoning": "...",
    "alternatives": ["..."]
}}"""

        messages = [{"role": "user", "content": user_message}]

        # 調用 LLM
        response = self.llm.call_llm(
            messages=messages,
            temperature=0.3,  # 降低溫度以提高一致性
        )

        # 解析響應
        return self._parse_llm_response(response, text)

    def _build_system_prompt(self, current_order_has_main: bool) -> str:
        """構建系統提示詞"""
        context_hint = ""
        if current_order_has_main:
            context_hint = "用戶已經點了主食，所以後續的飲料或點心相關詞更可能是飲料或點心。"

        return f"""你是點餐系統的路由分類器。你的工作是理解用戶的訂購意圖，並將其分類到正確的商品類別。

商品類別定義:
- riceball (飯糰): 「飯糰」、「米種」、「口味」等相關詞
- egg_pancake (蛋餅): 「蛋餅」、「雞蛋」等相關詞
- carrier (漢堡/吐司/饅頭): 「漢堡」、「吐司」、「饅頭」、「貝果」等載體
- drink (飲料): 「豆漿」、「紅茶」、「奶茶」、「飲料」等
- snack (點心): 「雞塊」、「薯條」、「炸物」等點心
- jam_toast (果醬吐司): 「草莓」、「花生」、「蒜香」等果醬吐司
- unknown: 無法確定或不屬於以上任何類別

{context_hint}

你必須回傳有效的 JSON，不要添加任何額外的文字。"""

    def _build_context_str(self, context: SessionContext) -> str:
        """從上下文構建提示字符串"""
        parts = []

        if context.cart_items:
            parts.append(f"購物車中已有: {', '.join(context.cart_items)}")

        if context.has_main_item:
            parts.append("已有主食")

        if context.has_drink:
            parts.append("已有飲料")

        if context.pending_items:
            parts.append(f"待補槽: {', '.join(context.pending_items)}")

        if not parts:
            parts.append("購物車為空，這是一個新訂單")

        return f"會話上下文: {' | '.join(parts)}"

    def _parse_llm_response(self, response: Dict[str, Any], text: str) -> Dict[str, Any]:
        """解析 LLM 響應"""
        try:
            # 從響應中提取消息內容
            message = response["choices"][0]["message"]
            content = message.get("content", "").strip()

            # 嘗試解析 JSON
            parsed = json.loads(content)

            # 驗證必要欄位
            route_type = parsed.get("route_type", "unknown")
            confidence = float(parsed.get("confidence", 0.0))
            reasoning = parsed.get("reasoning", "")
            alternatives = parsed.get("alternatives", [])

            return {
                "route_type": route_type,
                "confidence": confidence,
                "reasoning": reasoning,
                "alternatives": alternatives,
                "trace": {"source": "llm", "raw_content": content[:100]},  # 只保留前 100 字用於調試
            }
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            logger.warning(f"Failed to parse LLM response for '{text}': {e}")
            return {
                "route_type": "unknown",
                "confidence": 0.0,
                "reasoning": "無法解析 LLM 響應",
                "alternatives": [],
                "trace": {"error": str(e), "parse_failure": True},
            }

    def clear_cache(self):
        """清除快取"""
        self._cache.clear()
