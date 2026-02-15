# src/services/tts_service.py
"""TTS Service - 文字轉語音服務 (使用 Edge TTS)"""

import asyncio
from loguru import logger
import os
import tempfile
from typing import Optional


class TTSService:
    """使用 Edge TTS 的文字轉語音服務"""

    # 可用的中文語音
    VOICES = {
        "female": "zh-TW-HsiaoChenNeural",  # 台灣女聲
        "male": "zh-TW-YunJheNeural",       # 台灣男聲
        "female_cn": "zh-CN-XiaoxiaoNeural", # 中國女聲
        "male_cn": "zh-CN-YunxiNeural",      # 中國男聲
    }

    def __init__(self, voice: str = "female", rate: str = "+0%", volume: str = "+0%"):
        """
        初始化 TTS 服務

        Args:
            voice: 語音類型 ("female", "male", "female_cn", "male_cn") 或完整語音名稱
            rate: 語速調整 (如 "+10%", "-20%", "+0%")
            volume: 音量調整 (如 "+10%", "-20%", "+0%")
        """
        # 如果是預設的 key，轉換為完整語音名稱
        self.voice = self.VOICES.get(voice, voice)
        self.rate = rate
        self.volume = volume
        self.engine = True  # 標記為可用

        # 確保輸出目錄存在
        self.output_dir = os.path.join(tempfile.gettempdir(), "tts_output")
        os.makedirs(self.output_dir, exist_ok=True)

        logger.info(f"[TTS] Edge TTS 已初始化，語音: {self.voice}")

    def speak(self, text: str, save_to_file: Optional[str] = None) -> dict:
        """
        將文字轉為語音（同步包裝）

        Args:
            text: 要轉為語音的文字
            save_to_file: 可選，保存為 mp3 文件的路徑

        Returns:
            {
                "status": "success" 或 "error",
                "text": 原始文字,
                "file_path": 保存文件路徑（如果有）,
                "error": 錯誤信息（如果有）
            }
        """
        try:
            # 在新的事件循環中運行異步方法
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result = loop.run_until_complete(self._speak_async(text, save_to_file))
            finally:
                loop.close()
            return result
        except Exception as e:
            logger.error(f"[TTS] 轉語音失敗: {e}")
            return {
                "status": "error",
                "text": text,
                "error": str(e)
            }

    async def _speak_async(self, text: str, save_to_file: Optional[str] = None) -> dict:
        """
        將文字轉為語音（異步實現）
        """
        try:
            import edge_tts

            # 決定輸出路徑
            if save_to_file:
                output_path = save_to_file
            else:
                # 使用臨時檔案
                output_path = os.path.join(self.output_dir, f"tts_{hash(text) & 0xFFFFFFFF}.mp3")

            # 使用 Edge TTS 生成語音
            communicate = edge_tts.Communicate(
                text,
                self.voice,
                rate=self.rate,
                volume=self.volume
            )
            await communicate.save(output_path)

            logger.info(f"[TTS] 已生成語音: {output_path}")

            return {
                "status": "success",
                "text": text,
                "file_path": output_path
            }

        except ImportError:
            logger.error("[TTS] 未安裝 edge-tts，請執行: pip install edge-tts")
            return {
                "status": "error",
                "text": text,
                "error": "edge-tts 未安裝"
            }
        except Exception as e:
            logger.error(f"[TTS] Edge TTS 錯誤: {e}")
            return {
                "status": "error",
                "text": text,
                "error": str(e)
            }

    def get_properties(self) -> dict:
        """獲取 TTS 引擎的當前屬性"""
        return {
            "engine": "edge-tts",
            "voice": self.voice,
            "rate": self.rate,
            "volume": self.volume,
            "available_voices": list(self.VOICES.keys())
        }

    def set_voice(self, voice: str):
        """設置語音"""
        self.voice = self.VOICES.get(voice, voice)

    def set_rate(self, rate: str):
        """設置語速 (如 '+10%', '-20%')"""
        self.rate = rate

    def set_volume(self, volume: str):
        """設置音量 (如 '+10%', '-20%')"""
        self.volume = volume
