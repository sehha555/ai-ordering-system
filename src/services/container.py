# src/services/container.py
"""服務容器 — 集中管理應用程式層級的服務實例，避免循環依賴"""
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.dm.session_store import SessionStore
    from src.services.llm_tool_caller import LLMToolCaller
    from src.dm.tool_registry import ToolRegistry
    from src.services.asr_service import ASRService

# 服務實例（由 app.py 模組層級初始化）
session_store: "SessionStore | None" = None
llm_caller: "LLMToolCaller | None" = None
tool_registry: "ToolRegistry | None" = None
asr_service: "ASRService | None" = None
