"""
實時語音點餐 CLI - 支持麥克風直接輸入
"""

import sys
from pathlib import Path
import numpy as np
import sounddevice as sd
from dotenv import load_dotenv

# Add project root to Python path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from src.services.asr_service import ASRService
from src.services.tts_service import TTSService
from src.dm.dialogue_manager import DialogueManager
from src.dm.session_store import InMemorySessionStore

# Load environment variables
load_dotenv()


class VoiceOrderingCLI:
    """實時語音點餐系統"""

    def __init__(self):
        """初始化系統"""
        print("\n" + "=" * 70)
        print("源飯糰 AI 語音點餐系統 - 語音模式")
        print("=" * 70)
        print("\n初始化服務中...\n")

        # 初始化服務
        self.asr_service = ASRService(model_size="base", language="zh")
        self.tts_service = TTSService(language="zh", rate=150)
        self.session_store = InMemorySessionStore()

        # 初始化對話管理器
        # 注意: 先使用基本的 order_router 流程（已驗證穩定）
        # 如需要 LLM 增強，可在後續升級
        self.dialogue_manager = DialogueManager(store=self.session_store)
        self.session_id = "voice_user_001"

        # 錄音參數
        self.sample_rate = 16000  # 16kHz
        self.duration = None  # 動態錄音
        self.channels = 1  # 單聲道

        if self.asr_service.model:
            print("[OK] ASR 服務已就緒")
        else:
            print("[警告] ASR 模型未加載，語音識別可能不可用")

        if self.tts_service.engine:
            print("[OK] TTS 服務已就緒")
        else:
            print("[警告] TTS 引擎未初始化，語音回應可能不可用")

        print("\n系統初始化完成！\n")
        print("模式: 標準菜單路由 (穩定版)")
        print("支援菜單: 飯糰、蛋餅、漢堡、雞塊、吐司、套餐等\n")
        print("使用說明:")
        print("  - 直接按 Enter 進行語音輸入（自動錄 5 秒）")
        print("  - 輸入文字後按 Enter 進行文字輸入")
        print("  - 輸入 'quit' 退出系統\n")

    def record_audio(self, duration: int = 5) -> np.ndarray:
        """
        實時錄音 - 錄製指定時間的音訊

        Args:
            duration: 錄音時長（秒），預設 5 秒

        Returns:
            錄音的 numpy 陣列
        """
        print(f"\n錄音開始（{duration} 秒）...")
        print("請對著麥克風說話...")

        try:
            # 使用 sounddevice 進行錄音
            audio_data = sd.rec(
                int(duration * self.sample_rate),
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype=np.int16,
            )
            sd.wait()  # 等待錄音完成

            print("錄音完成！正在處理...")
            return audio_data.flatten()

        except Exception as e:
            print(f"[錯誤] 錄音失敗: {e}")
            print("[提示] 請確認您的麥克風已連接並可用")
            return np.array([])

    def process_voice_order(self):
        """處理語音點餐"""
        print("=" * 70)
        print("進入語音點餐模式")
        print("=" * 70)
        print("提示: 空輸入 = 語音; 文字 = 文字輸入; 'quit' = 退出\n")

        while True:
            user_input = input(">>> ").strip()

            if user_input.lower() == "quit":
                print("\n感謝使用，再見！\n")
                break

            if user_input == "":
                # 空輸入 = 用麥克風
                print("\n啟動麥克風語音輸入...")
                audio_data = self.record_audio()

                if len(audio_data) == 0:
                    print("[警告] 未錄製到音訊")
                    continue

                # 直接用字節流識別，無需保存檔案
                try:
                    # 確保音訊數據格式正確
                    if len(audio_data.shape) > 1:
                        audio_data = audio_data.flatten()

                    # ASR 識別（使用字節流方式，不需要檔案）
                    print("\nASR 識別中...")

                    # 轉換為字節
                    audio_bytes = audio_data.astype(np.int16).tobytes()

                    # 使用 transcribe_bytes 方法（無需 FFmpeg）
                    asr_result = self.asr_service.transcribe_bytes(
                        audio_bytes,
                        sample_rate=self.sample_rate
                    )

                    if asr_result.get("error"):
                        print(f"[錯誤] ASR 識別失敗: {asr_result['error']}")
                        continue

                    user_text = asr_result.get("text", "").strip()
                    print(f"\n您說: {user_text}")

                    if not user_text:
                        print("[警告] 未識別到語音內容，請重試")
                        continue

                    # 對話管理器處理
                    print("店員思考中...")
                    try:
                        response = self.dialogue_manager.handle(self.session_id, user_text)
                        print(f"店員: {response}")

                        # TTS 播放回應
                        if self.tts_service.engine:
                            print("\n播放語音回應...\n")
                            self.tts_service.speak(response)
                        else:
                            print("[警告] TTS 不可用，無法播放語音")
                    except Exception as dm_error:
                        print(f"[對話管理器錯誤] {dm_error}")
                        print("請重試或輸入簡化的菜單名稱")

                except Exception as error:
                    print(f"[錯誤] 音訊處理失敗: {error}")
                    import traceback
                    traceback.print_exc()

            else:
                # 文字輸入（用於測試或無麥克風時）
                print(f"\n您說: {user_input}")

                # 對話管理器處理
                print("店員思考中...")
                response = self.dialogue_manager.handle(self.session_id, user_input)
                print(f"店員: {response}\n")

                # 嘗試播放 TTS
                if self.tts_service.engine:
                    print("播放語音回應...")
                    self.tts_service.speak(response)

    def run(self):
        """運行主程序"""
        print("\n" + "=" * 70)
        print("選擇輸入模式")
        print("=" * 70)
        print("1. 語音模式 (用麥克風講話) - 推薦")
        print("2. 文字模式 (手動輸入)")
        print("3. 離開")
        print()

        choice = input("請選擇 (1-3): ").strip()

        if choice == "1":
            print("\n進入語音點餐模式\n")
            self.process_voice_order()
        elif choice == "2":
            print("\n進入文字點餐模式\n")
            self.process_text_order()
        elif choice == "3":
            print("\n再見！\n")
        else:
            print("無效選擇\n")

    def process_text_order(self):
        """處理文字點餐"""
        print("提示: 輸入 'quit' 退出點餐\n")

        while True:
            user_input = input("您: ").strip()

            if user_input.lower() == "quit":
                print("\n感謝使用，再見！\n")
                break

            if not user_input:
                continue

            # 對話管理器處理
            response = self.dialogue_manager.handle(self.session_id, user_input)
            print(f"店員: {response}\n")

            # 嘗試播放 TTS
            if self.tts_service.engine:
                print("[播放語音回應...]")
                self.tts_service.speak(response)
                print()


def main():
    """程序入口"""
    try:
        cli = VoiceOrderingCLI()
        cli.run()
    except KeyboardInterrupt:
        print("\n\n系統已停止")
    except Exception as e:
        print(f"\n系統錯誤: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    main()
