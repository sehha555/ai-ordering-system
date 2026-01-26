"""
LLM 配置示例
============

如何啟用 LLM 功能（保守混合模式 - Phase 1）
"""

from src.dm.dialogue_manager import DialogueManager
from src.dm.llm_router import LLMRouter
from src.dm.llm_clarifier import LLMClarifier
from src.services.llm_tool_caller import LLMToolCaller
from src.dm.session_store import InMemorySessionStore


def create_dm_with_llm():
    """建立啟用 LLM 的對話管理器"""
    
    # 第一步：初始化 LLM Tool Caller（連接到 LM Studio）
    llm = LLMToolCaller(
        base_url="http://127.0.0.1:1234/v1/chat/completions",
        model="qwen2.5-14b-instruct-1m",
        timeout=30  # 允許最多 30 秒的 LLM 調用
    )
    
    # 第二步：初始化 LLM Router（用於分類未知項目）
    llm_router = LLMRouter(
        llm=llm,
        timeout=10,  # LLM 分類超時
        confidence_threshold=0.75  # 信心度閾值（>0.75 才使用）
    )
    
    # 第三步：初始化 LLM Clarifier（用於生成自然澄清問題）
    llm_clarifier = LLMClarifier(llm=llm)
    
    # 第四步：建立 Dialogue Manager 並啟用 LLM
    dm = DialogueManager(
        store=InMemorySessionStore(),
        llm_router=llm_router,        # 傳入 LLM 路由器
        llm_clarifier=llm_clarifier,  # 傳入 LLM 澄清器
        llm_enabled=True              # 啟用 LLM 功能
    )
    
    return dm


def create_dm_without_llm():
    """建立不使用 LLM 的對話管理器（預設）"""
    dm = DialogueManager(
        store=InMemorySessionStore(),
        llm_enabled=False  # LLM 功能禁用（預設安全模式）
    )
    return dm


if __name__ == "__main__":
    # 使用示例

    # 啟用 LLM
    print("建立 Dialogue Manager（LLM 啟用）...")
    dm_with_llm = create_dm_with_llm()
    print("[OK] LLM Router: " + str(dm_with_llm.llm_router is not None))
    print("[OK] LLM Clarifier: " + str(dm_with_llm.llm_clarifier is not None))
    print()

    # 不使用 LLM（推薦的預設配置）
    print("建立 Dialogue Manager（LLM 禁用）...")
    dm_without_llm = create_dm_without_llm()
    print("[OK] LLM Router: " + str(dm_without_llm.llm_router is not None))
    print("[OK] LLM Clarifier: " + str(dm_without_llm.llm_clarifier is not None))
