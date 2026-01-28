"""LLM 對話處理器 - 主要的 LLM 對話入口"""
import json
from typing import Optional, Dict, Any
from requests.exceptions import Timeout, RequestException

from src.services.llm_tool_caller import LLMToolCaller
from src.dm.tool_registry import ToolRegistry
from src.dm.dialogue_manager import DialogueManager
from src.dm.system_prompts import SystemPromptBuilder
from src.dm.session_context import SessionContext


class LLMConversationProcessor:
    """
    LLM 對話處理器 - 協調 LLM、工具註冊表和會話管理
    """

    def __init__(
        self,
        llm: LLMToolCaller,
        tool_registry: ToolRegistry,
        dialogue_manager: DialogueManager,
        timeout: int = 30,
        fallback_enabled: bool = True,
    ):
        """
        初始化 LLM 對話處理器

        Args:
            llm: LLMToolCaller 實例
            tool_registry: ToolRegistry 實例
            dialogue_manager: DialogueManager 實例
            timeout: LLM 請求超時時間（秒）
            fallback_enabled: 是否啟用回退到傳統對話管理器
        """
        self.llm = llm
        self.tool_registry = tool_registry
        self.dialogue_manager = dialogue_manager
        self.timeout = timeout
        self.fallback_enabled = fallback_enabled
        self.system_prompt_builder = SystemPromptBuilder()

    def handle(self, session_id: str, user_text: str) -> str:
        """
        處理用戶輸入並返回助手回覆

        Args:
            session_id: 會話 ID
            user_text: 用戶輸入文本

        Returns:
            助手回覆
        """
        try:
            # 1. 獲取會話
            session = self.dialogue_manager.store.get(session_id)
            self.dialogue_manager._ensure_session_defaults(session)

            # 2. 設置工具註冊表的會話 ID
            self.tool_registry.set_session_id(session_id)

            # 3. 構建系統提示
            session_context = SessionContext.from_session(session)
            system_prompt = self.system_prompt_builder.build(session_context)

            # 4. 構建對話歷史（轉換為 OpenAI 格式）
            history = self._build_message_history(session)

            # 5. 獲取工具定義、映射和允許參數
            tools_schema = self.tool_registry.get_tools_schema()
            tool_map = self.tool_registry.get_tool_map()
            allowed_args = self.tool_registry.get_allowed_args()

            # 6. 調用 LLM 執行對話回合
            result = self.llm.run_turn(
                system_prompt=system_prompt,
                user_text=user_text,
                history=history,
                tools_schema=tools_schema,
                tool_map=tool_map,
                allowed_args=allowed_args,
            )

            # 7. 處理返回結果
            if result.get("ok"):
                # 成功：更新會話歷史並返回回覆
                new_history = result.get("history", history)
                session["history"] = self._extract_session_history(new_history)
                assistant_text = result.get("assistant_text", "")
                return assistant_text

            else:
                # LLM 失敗（如超出最大步數、工具執行出錯等）
                error_msg = result.get("error", "LLM 處理失敗")
                return self._handle_llm_failure(session_id, user_text, error_msg)

        except (Timeout, RequestException) as e:
            # 網路錯誤或超時
            return self._handle_timeout_or_network_error(session_id, user_text, e)

        except json.JSONDecodeError as e:
            # JSON 解析失敗
            return self._handle_json_error(session_id, user_text, e)

        except Exception as e:
            # 未預期的異常
            return self._handle_unexpected_error(session_id, user_text, e)

    # ============ 輔助方法 ============

    def _build_message_history(self, session: Dict[str, Any]) -> list:
        """
        將會話歷史轉換為 OpenAI 消息格式

        Args:
            session: 會話字典

        Returns:
            OpenAI 格式的消息列表
        """
        history = session.get("history", [])
        messages = []

        # 會話歷史可能是簡單的字符串列表，需要轉換為消息格式
        # 交替出現用戶和助手消息
        for i, item in enumerate(history):
            if isinstance(item, dict):
                # 已經是消息格式
                messages.append(item)
            else:
                # 簡單的字符串，根據位置推斷角色
                # 偶數位置是用戶，奇數位置是助手
                role = "user" if i % 2 == 0 else "assistant"
                messages.append({"role": role, "content": str(item)})

        return messages

    def _extract_session_history(self, llm_messages: list) -> list:
        """
        從 OpenAI 消息格式提取簡化的會話歷史

        Args:
            llm_messages: OpenAI 格式的消息列表

        Returns:
            簡化的歷史列表
        """
        history = []
        for msg in llm_messages:
            if msg.get("role") != "system":
                # 跳過系統消息，只保留用戶和助手消息
                content = msg.get("content", "")
                if content:
                    history.append(content)
        return history

    def _handle_timeout_or_network_error(
        self,
        session_id: str,
        user_text: str,
        error: Exception,
    ) -> str:
        """
        處理網路超時或連接錯誤

        Args:
            session_id: 會話 ID
            user_text: 用戶輸入
            error: 異常對象

        Returns:
            回退回覆或錯誤消息
        """
        error_type = type(error).__name__
        error_msg = str(error)

        if self.fallback_enabled:
            # 回退到傳統對話管理器
            try:
                fallback_response = self.dialogue_manager.handle(session_id, user_text)
                return fallback_response
            except Exception as fallback_error:
                # 回退也失敗
                return f"系統暫時無法回應，請稍後再試（{error_type}）"

        else:
            # 不啟用回退，直接返回錯誤消息
            return f"通訊失敗：{error_type}，請稍後再試"

    def _handle_json_error(
        self,
        session_id: str,
        user_text: str,
        error: json.JSONDecodeError,
    ) -> str:
        """
        處理 JSON 解析錯誤

        Args:
            session_id: 會話 ID
            user_text: 用戶輸入
            error: 異常對象

        Returns:
            回退回覆或錯誤消息
        """
        if self.fallback_enabled:
            # 回退到傳統對話管理器
            try:
                fallback_response = self.dialogue_manager.handle(session_id, user_text)
                return fallback_response
            except Exception:
                return "系統遇到問題，請稍後再試"

        else:
            return "數據解析失敗，請稍後再試"

    def _handle_llm_failure(
        self,
        session_id: str,
        user_text: str,
        error_msg: str,
    ) -> str:
        """
        處理 LLM 處理失敗（如超出最大步數等）

        Args:
            session_id: 會話 ID
            user_text: 用戶輸入
            error_msg: 錯誤消息

        Returns:
            回退回覆或錯誤消息
        """
        if self.fallback_enabled:
            # 回退到傳統對話管理器
            try:
                fallback_response = self.dialogue_manager.handle(session_id, user_text)
                return fallback_response
            except Exception:
                return "處理您的請求時出現問題，請稍後再試"

        else:
            if error_msg == "max_steps_exceeded":
                return "對話步驟過多，無法完成處理"
            else:
                return f"無法完成操作：{error_msg}"

    def _handle_unexpected_error(
        self,
        session_id: str,
        user_text: str,
        error: Exception,
    ) -> str:
        """
        處理未預期的異常

        Args:
            session_id: 會話 ID
            user_text: 用戶輸入
            error: 異常對象

        Returns:
            回退回覆或錯誤消息
        """
        error_type = type(error).__name__

        if self.fallback_enabled:
            # 回退到傳統對話管理器
            try:
                fallback_response = self.dialogue_manager.handle(session_id, user_text)
                return fallback_response
            except Exception:
                return "系統遇到內部錯誤，請稍後再試"

        else:
            return f"內部錯誤：{error_type}，請稍後再試"
