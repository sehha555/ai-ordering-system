# src/services/asr_service.py
"""
ASR Service - 語音辨識服務 (使用 OpenAI Whisper)
"""

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


class ASRService:
    """使用 Whisper 的語音辨識服務"""

    def __init__(self, model_size: str = "base", language: str = "zh"):
        """
        初始化 ASR 服務

        Args:
            model_size: Whisper 模型大小 (tiny, base, small, medium, large)
            language: 語言代碼 (zh, en, etc.)
        """
        try:
            import whisper
            self.whisper = whisper
            self.model = whisper.load_model(model_size)
            self.language = language
            logger.info(f"[ASR] Whisper {model_size} 模型已加載")
        except ImportError:
            logger.error("[ASR] 未安裝 openai-whisper，請執行: pip install openai-whisper")
            self.model = None
            self.whisper = None

    def transcribe(self, audio_path: str, language: Optional[str] = None) -> dict:
        """
        將語音文件轉為文字

        Args:
            audio_path: 音訊文件路徑 (支持 mp3, wav, m4a, flac 等)
            language: 語言代碼（可覆蓋預設值）

        Returns:
            {
                "text": "辨識出的文字",
                "language": "檢測到的語言",
                "confidence": 0.0-1.0,
                "segments": [...]
            }
        """
        if self.model is None:
            return {
                "text": "",
                "error": "Whisper 模型未加載",
                "language": None,
                "confidence": 0.0
            }

        try:
            if not os.path.exists(audio_path):
                return {
                    "text": "",
                    "error": f"音訊文件不存在: {audio_path}",
                    "language": None,
                    "confidence": 0.0
                }

            # 使用 Whisper 進行語音識別
            result = self.model.transcribe(
                audio_path,
                language=language or self.language,
                verbose=False
            )

            return {
                "text": result.get("text", "").strip(),
                "language": result.get("language", self.language),
                "confidence": 0.95,  # Whisper 不提供原生置信度，但精度較高
                "segments": result.get("segments", [])
            }

        except Exception as e:
            logger.error(f"[ASR] 轉錄失敗: {e}")
            return {
                "text": "",
                "error": str(e),
                "language": None,
                "confidence": 0.0
            }

    def transcribe_bytes(self, audio_bytes: bytes, sample_rate: int = 16000) -> dict:
        """
        將語音字節轉為文字（用於實時語音流）

        Args:
            audio_bytes: 音訊字節數據
            sample_rate: 採樣率 (Hz)

        Returns:
            識別結果字典
        """
        if self.model is None:
            return {
                "text": "",
                "error": "Whisper 模型未加載",
                "language": None,
                "confidence": 0.0
            }

        try:
            import tempfile
            import numpy as np

            # 將字節保存為臨時 wav 文件
            audio_array = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0

            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                import soundfile as sf
                sf.write(tmp.name, audio_array, sample_rate)
                temp_path = tmp.name

            try:
                # 使用 transcribe_path 方法
                result = self.transcribe(temp_path)
            finally:
                os.unlink(temp_path)

            return result

        except Exception as e:
            logger.error(f"[ASR] 字節轉錄失敗: {e}")
            return {
                "text": "",
                "error": str(e),
                "language": None,
                "confidence": 0.0
            }
