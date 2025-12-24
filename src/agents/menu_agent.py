# src/agents/menu_agent.py
"""Menu Agent - 菜單管理"""


class MenuAgent:
    """菜單代理"""
    
    def __init__(self, llm_service):
        self.llm_service = llm_service
    
    def get_menu(self) -> str:
        """取得菜單資訊"""
        return """
【源飯糰菜單】

飯糰類 ($55)
- 培根飯糰
- 火腿飯糰
- 鮪魚飯糰
- 素食飯糰

飲料類
- 豆漿 ($20)
- 紅茶 ($25)
- 奶茶 ($30)
        """
