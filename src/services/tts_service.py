# src/services/tts_service.py
"""TTS Service - 文字轉語音服務 (使用 pyttsx3)"""

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


class TTSService:
    """使用 pyttsx3 的文字轉語音服務"""

    def __init__(self, language: str = "zh", rate: int = 150, volume: float = 1.0):
        """
        初始化 TTS 服務

        Args:
            language: 語言 (zh 中文, en 英文, etc.)
            rate: 語速 (50-300，越高越快)
            volume: 音量 (0.0-1.0)
        """
        try:
            import pyttsx3
            self.engine = pyttsx3.init()
            self.language = language

            # 設置語速
            self.engine.setProperty("rate", rate)

            # 設置音量
            self.engine.setProperty("volume", volume)

            # 嘗試設置中文語言
            self._setup_language(language)

            logger.info("[TTS] pyttsx3 引擎已初始化")
        except ImportError:
            logger.error("[TTS] 未安裝 pyttsx3，請執行: pip install pyttsx3")
            self.engine = None

    def _setup_language(self, language: str):
        """設置語言"""
        try:
            voices = self.engine.getProperty("voices")
            if language == "zh":
                # 嘗試找到中文語音
                for voice in voices:
                    if "Chinese" in voice.name or "中文" in voice.name:
                        self.engine.setProperty("voice", voice.id)
                        logger.info(f"[TTS] 使用中文語音: {voice.name}")
                        return
            elif language == "en":
                # 英文語音
                for voice in voices:
                    if "English" in voice.name:
                        self.engine.setProperty("voice", voice.id)
                        logger.info(f"[TTS] 使用英文語音: {voice.name}")
                        return

            # 使用預設語音
            if voices:
                self.engine.setProperty("voice", voices[0].id)
                logger.info(f"[TTS] 使用預設語音: {voices[0].name}")
        except Exception as e:
            logger.warning(f"[TTS] 設置語言失敗: {e}，使用預設語音")

    def speak(self, text: str, save_to_file: Optional[str] = None) -> dict:
        """
        將文字轉為語音

        Args:
            text: 要轉為語音的文字
            save_to_file: 可選，保存為 wav 文件的路徑

        Returns:
            {
                "status": "success" 或 "error",
                "text": 原始文字,
                "file_path": 保存文件路徑（如果有）,
                "error": 錯誤信息（如果有）
            }
        """
        if self.engine is None:
            return {
                "status": "error",
                "text": text,
                "error": "TTS 引擎未初始化"
            }

        try:
            if save_to_file:
                # 保存到文件
                self.engine.save_to_file(text, save_to_file)
                self.engine.runAndWait()
                return {
                    "status": "success",
                    "text": text,
                    "file_path": save_to_file
                }
            else:
                # 直接播放
                self.engine.say(text)
                self.engine.runAndWait()
                return {
                    "status": "success",
                    "text": text,
                    "file_path": None
                }

        except Exception as e:
            logger.error(f"[TTS] 轉語音失敗: {e}")
            return {
                "status": "error",
                "text": text,
                "error": str(e)
            }

    def speak_async(self, text: str) -> dict:
        """
        異步將文字轉為語音（不等待完成）

        Args:
            text: 要轉為語音的文字

        Returns:
            {
                "status": "queued" 或 "error",
                "text": 原始文字,
                "error": 錯誤信息（如果有）
            }
        """
        if self.engine is None:
            return {
                "status": "error",
                "text": text,
                "error": "TTS 引擎未初始化"
            }

        try:
            self.engine.say(text)
            # 不調用 runAndWait()，讓它在後台運行
            return {
                "status": "queued",
                "text": text
            }

        except Exception as e:
            logger.error(f"[TTS] 非同步轉語音失敗: {e}")
            return {
                "status": "error",
                "text": text,
                "error": str(e)
            }

    def get_properties(self) -> dict:
        """獲取 TTS 引擎的當前屬性"""
        if self.engine is None:
            return {}

        return {
            "rate": self.engine.getProperty("rate"),
            "volume": self.engine.getProperty("volume"),
            "voices": [{"id": v.id, "name": v.name, "languages": v.languages}
                      for v in self.engine.getProperty("voices")]
        }

    def set_rate(self, rate: int):
        """設置語速"""
        if self.engine is not None:
            self.engine.setProperty("rate", min(300, max(50, rate)))

    def set_volume(self, volume: float):
        """設置音量"""
        if self.engine is not None:
            self.engine.setProperty("volume", min(1.0, max(0.0, volume)))
