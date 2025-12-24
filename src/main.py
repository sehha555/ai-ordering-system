# src/main.py
"""
Yuan Restaurant AI Voice Ordering System - Main Entry Point
"""

import sys
from pathlib import Path
from dotenv import load_dotenv

# Add project root to Python path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from src.services.llm_service import LLMService
from src.services.asr_service import ASRService
from src.services.tts_service import TTSService
from src.agents.menu_agent import MenuAgent
from src.agents.order_agent import OrderAgent

# Load environment variables
load_dotenv()


class OrderingSystem:
    """Voice ordering system main class"""

    def __init__(self):
        """Initialize system"""
        print("源飯糰 AI 語音點餐系統初始化中...\n")

        # Initialize services
        self.llm_service = LLMService()
        self.asr_service = ASRService()
        self.tts_service = TTSService()

        # Initialize agents
        self.menu_agent = MenuAgent(self.llm_service)
        self.order_agent = OrderAgent(self.llm_service)

        print("系統初始化完成\n")

    def run(self):
        """Run main ordering system loop"""
        print("=" * 60)
        print("歡迎使用源飯糰 AI 語音點餐系統")
        print("=" * 60)
        print("\n功能選單:")
        print("1. 開始點餐")
        print("2. 查看菜單")
        print("3. 測試 LLM 連線")
        print("4. 離開系統")
        print()

        while True:
            choice = input("請選擇功能 (1-4): ").strip()

            if choice == "1":
                self.start_ordering()
            elif choice == "2":
                self.show_menu()
            elif choice == "3":
                self.test_llm()
            elif choice == "4":
                print("\n感謝使用,再見!\n")
                break
            else:
                print("無效的選擇,請重新輸入\n")

    def start_ordering(self):
        """Start ordering process"""
        print("\n" + "=" * 60)
        print("語音點餐開始")
        print("=" * 60)
        print("提示: 輸入 'quit' 結束點餐\n")

        order_state = {
            "items": [],
            "total": 0,
            "dine_option": None,
        }

        while True:
            user_input = input("客人: ").strip()

            if user_input.lower() == "quit":
                print("\n點餐流程結束\n")
                break

            if not user_input:
                continue

            response = self.order_agent.process_order(user_input, order_state)
            print(f"店員: {response}\n")

    def show_menu(self):
        """Display menu"""
        print("\n" + "=" * 60)
        print("菜單")
        print("=" * 60)

        menu_info = self.menu_agent.get_menu()
        print(menu_info)
        print()

    def test_llm(self):
        """Test LLM connection"""
        print("\n" + "=" * 60)
        print("測試 LLM 連線")
        print("=" * 60)

        test_prompt = "你是源飯糰的點餐店員,請用一句簡短中文說:歡迎光臨,請問要點什麼?"

        try:
            response = self.llm_service.call_llm(test_prompt)
            print(f"LLM 回應成功:\n{response}\n")
        except Exception as e:
            print(f"LLM 連線失敗: {e}\n")


def main():
    """Program entry point"""
    try:
        system = OrderingSystem()
        system.run()
    except KeyboardInterrupt:
        print("\n\n系統已停止")
    except Exception as e:
        print(f"\n系統錯誤: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
