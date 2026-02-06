# src/services/asr_service.py
"""ASR Service - 語音辨識服務 (使用 Qwen3-ASR)"""

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


class ASRService:
    """使用 Qwen3-ASR 的語音辨識服務"""

    # Qwen3-ASR 模型對應
    MODELS = {
        "small": "Qwen/Qwen3-ASR-Small",
        "turbo": "Qwen/Qwen3-ASR-Turbo",
        "large": "Qwen/Qwen3-ASR",
    }

    # 語言代碼對應 (Qwen3 使用完整語言名稱)
    LANGUAGE_MAP = {
        "zh": "Chinese",
        "en": "English",
        "ja": "Japanese",
        "ko": "Korean",
    }

    def __init__(self, model_size: str = "turbo", language: str = "zh"):
        """
        初始化 ASR 服務

        Args:
            model_size: 模型大小 ("small", "turbo", "large")
            language: 預設語言 (zh, en, ja, ko)
        """
        self.model = None
        self.language = language
        self.model_name = self.MODELS.get(model_size, self.MODELS["turbo"])

        try:
            from qwen_asr.inference.qwen3_asr import Qwen3ASRModel
            import torch

            # 檢測設備
            if torch.cuda.is_available():
                device = "cuda"
                logger.info(f"[ASR] 使用 GPU: {torch.cuda.get_device_name(0)}")
            else:
                device = "cpu"
                logger.info("[ASR] 使用 CPU（速度較慢）")

            logger.info(f"[ASR] 正在載入 Qwen3-ASR {self.model_name}...")
            self.model = Qwen3ASRModel.from_pretrained(
                self.model_name,
                device_map=device,
                torch_dtype=torch.float16 if device == "cuda" else torch.float32,
            )
            logger.info(f"[ASR] Qwen3-ASR {self.model_name} 模型已載入")

        except ImportError as e:
            logger.error(f"[ASR] 未安裝 qwen-asr，請執行: pip install qwen-asr")
            logger.error(f"[ASR] 錯誤詳情: {e}")
        except Exception as e:
            logger.error(f"[ASR] 模型載入失敗: {e}")

    def transcribe(self, audio_path: str, language: Optional[str] = None) -> dict:
        """
        將語音文件轉為文字

        Args:
            audio_path: 音訊文件路徑 (支持 mp3, wav, m4a, flac 等)
            language: 語言代碼（可覆蓋預設值，如 "zh", "en"）

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
                "error": "Qwen3-ASR 模型未載入",
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

            import sys
            print(f"[ASR] 開始轉錄: {audio_path}", file=sys.stderr, flush=True)

            # 轉換語言代碼為 Qwen3 格式
            lang_code = language or self.language
            qwen_language = self.LANGUAGE_MAP.get(lang_code, "Chinese")

            # 使用 Qwen3-ASR 進行語音識別
            results = self.model.transcribe(
                audio=audio_path,
                language=qwen_language,
            )

            # 取得第一個結果（單一音訊輸入）
            if results and len(results) > 0:
                result = results[0]
                full_text = result.text.strip() if result.text else ""
                detected_language = result.language if hasattr(result, 'language') else qwen_language

                print(f"[ASR] 轉錄完成: '{full_text}'", file=sys.stderr, flush=True)
                print(f"[ASR] 檢測語言: {detected_language}", file=sys.stderr, flush=True)

                if not full_text:
                    return {
                        "text": "",
                        "error": "語音內容為空或無法識別",
                        "language": detected_language,
                        "confidence": 0.0
                    }

                # 構建 segments（如果有時間戳記）
                segments = []
                if hasattr(result, 'words') and result.words:
                    for word in result.words:
                        segments.append({
                            "start": word.start if hasattr(word, 'start') else 0,
                            "end": word.end if hasattr(word, 'end') else 0,
                            "text": word.word if hasattr(word, 'word') else str(word),
                        })

                return {
                    "text": full_text,
                    "language": detected_language,
                    "confidence": 0.95,  # Qwen3-ASR 通常信心度很高
                    "segments": segments
                }
            else:
                return {
                    "text": "",
                    "error": "無法獲取轉錄結果",
                    "language": None,
                    "confidence": 0.0
                }

        except Exception as e:
            import sys
            import traceback
            print(f"[ASR] 轉錄失敗: {e}", file=sys.stderr, flush=True)
            traceback.print_exc()
            return {
                "text": "",
                "error": str(e),
                "language": None,
                "confidence": 0.0
            }
