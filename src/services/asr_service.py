# src/services/asr_service.py
"""ASR Service - 語音辨識服務 (Qwen3-ASR 或 SenseVoice-Small)"""

import io
import os
import re
from typing import Optional

import numpy as np
import soundfile as sf
from loguru import logger

_SENSEVOICE_TAG_RE = re.compile(r"<\|[^|]*\|>")
_DEFAULT_CONFIDENCE = 0.95


def _wav_bytes_to_ndarray(wav_bytes: bytes) -> tuple[np.ndarray, int]:
    """WAV bytes → (float32 ndarray, sample_rate)，用 soundfile 解碼"""
    data, sr = sf.read(io.BytesIO(wav_bytes), dtype="float32")
    return data, sr


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
            logger.error("[ASR] 未安裝 qwen-asr，請執行: pip install qwen-asr")
            logger.error(f"[ASR] 錯誤詳情: {e}")
        except Exception as e:
            logger.error(f"[ASR] 模型載入失敗: {e}")

    def _parse_qwen_results(self, results, qwen_language: str) -> dict:
        """共用結果解析：Qwen3-ASR transcribe 回傳值 → 標準 dict"""
        if not results or len(results) == 0:
            return {"text": "", "error": "無法獲取轉錄結果", "language": None, "confidence": 0.0}

        result = results[0]
        full_text = result.text.strip() if result.text else ""
        detected_language = result.language if hasattr(result, "language") else qwen_language

        logger.info("[ASR] 轉錄完成: '{}'", full_text)
        logger.info("[ASR] 檢測語言: {}", detected_language)

        if not full_text:
            return {
                "text": "",
                "error": "語音內容為空或無法識別",
                "language": detected_language,
                "confidence": 0.0,
            }

        segments = []
        if hasattr(result, "words") and result.words:
            for word in result.words:
                segments.append(
                    {
                        "start": word.start if hasattr(word, "start") else 0,
                        "end": word.end if hasattr(word, "end") else 0,
                        "text": word.word if hasattr(word, "word") else str(word),
                    }
                )

        return {
            "text": full_text,
            "language": detected_language,
            "confidence": _DEFAULT_CONFIDENCE,
            "segments": segments,
        }

    def transcribe(self, audio_path: str, language: Optional[str] = None) -> dict:
        if self.model is None:
            return {
                "text": "",
                "error": "Qwen3-ASR 模型未載入",
                "language": None,
                "confidence": 0.0,
            }

        try:
            if not os.path.exists(audio_path):
                return {
                    "text": "",
                    "error": f"音訊文件不存在: {audio_path}",
                    "language": None,
                    "confidence": 0.0,
                }

            logger.info("[ASR] 開始轉錄: {}", audio_path)
            lang_code = language or self.language
            qwen_language = self.LANGUAGE_MAP.get(lang_code, "Chinese")

            results = self.model.transcribe(audio=audio_path, language=qwen_language)
            return self._parse_qwen_results(results, qwen_language)

        except Exception as e:
            logger.exception("[ASR] 轉錄失敗")
            return {"text": "", "error": str(e), "language": None, "confidence": 0.0}

    def transcribe_bytes(self, wav_bytes: bytes, language: Optional[str] = None) -> dict:
        """WAV bytes 直接轉錄，省去 tempfile I/O"""
        if self.model is None:
            return {
                "text": "",
                "error": "Qwen3-ASR 模型未載入",
                "language": None,
                "confidence": 0.0,
            }

        try:
            ndarray, sr = _wav_bytes_to_ndarray(wav_bytes)
            lang_code = language or self.language
            qwen_language = self.LANGUAGE_MAP.get(lang_code, "Chinese")

            logger.info("[ASR] 開始轉錄（bytes 介面，sr={}）", sr)
            results = self.model.transcribe(audio=(ndarray, sr), language=qwen_language)
            return self._parse_qwen_results(results, qwen_language)

        except Exception as e:
            logger.exception("[ASR] 轉錄失敗（bytes 介面）")
            return {"text": "", "error": str(e), "language": None, "confidence": 0.0}


class SenseVoiceService:
    """使用 SenseVoice-Small 的語音辨識服務"""

    @staticmethod
    def _patch_funasr_tiktoken():
        """修復 funasr 1.3.1 打包缺陷：從 openai-whisper 複製缺失的 tiktoken 檔案"""
        import importlib.util
        import shutil
        from pathlib import Path

        funasr_spec = importlib.util.find_spec("funasr")
        whisper_spec = importlib.util.find_spec("whisper")
        if not funasr_spec or not funasr_spec.origin or not whisper_spec or not whisper_spec.origin:
            return

        funasr_assets = (
            Path(funasr_spec.origin).parent / "models" / "sense_voice" / "whisper_lib" / "assets"
        )
        whisper_assets = Path(whisper_spec.origin).parent / "assets"
        tiktoken_src = whisper_assets / "multilingual.tiktoken"
        tiktoken_dst = funasr_assets / "multilingual.tiktoken"

        if tiktoken_src.exists() and not tiktoken_dst.exists():
            funasr_assets.mkdir(parents=True, exist_ok=True)
            shutil.copy2(tiktoken_src, tiktoken_dst)
            logger.info("[ASR] 已修復 funasr whisper_lib/assets/multilingual.tiktoken")

    def __init__(
        self, model_id: str = "FunAudioLLM/SenseVoiceSmall", language: str = "zh", hub: str = "hf"
    ):
        self.model = None
        self.language = language
        self.model_name = model_id

        try:
            # 修復 funasr 1.3.1 打包缺陷：wheel 未包含 whisper_lib/assets/
            # tiktoken 檔案與 openai-whisper 套件完全相同，偵測到缺失時自動複製
            self._patch_funasr_tiktoken()

            from funasr import AutoModel
            import torch

            device = "cuda" if torch.cuda.is_available() else "cpu"

            # ModelScope hub 離線優先：cache 存在時直接用本地路徑，避免 modelscope.cn 校驗 hang
            resolved_model = model_id
            if hub == "ms":
                import os

                cache_dir = os.path.join(
                    os.path.expanduser("~"),
                    ".cache",
                    "modelscope",
                    "hub",
                    "models",
                    *model_id.split("/"),
                )
                if os.path.exists(os.path.join(cache_dir, "model.pt")):
                    resolved_model = cache_dir
                    logger.info(f"[ASR] 使用本地快取: {resolved_model}")

            logger.info(f"[ASR] 正在載入 SenseVoice {resolved_model} ({device}, hub={hub})...")
            self.model = AutoModel(
                model=resolved_model,
                hub=hub,
                device=device,
                disable_update=True,
            )
            logger.info("[ASR] SenseVoice 模型已載入")
        except ImportError:
            logger.error("[ASR] 未安裝 funasr，請執行: pip install funasr")
        except Exception as e:
            logger.error(f"[ASR] SenseVoice 載入失敗: {e}")

    def _parse_sensevoice_result(self, res, language: str) -> dict:
        """共用結果解析：SenseVoice generate 回傳值 → 標準 dict"""
        text = res[0]["text"].strip() if res else ""
        # ModelScope 版 SenseVoice 輸出含特殊 tag，需清除
        text = _SENSEVOICE_TAG_RE.sub("", text).strip()
        logger.info("[ASR] SenseVoice 轉錄完成: '{}'", text)
        return {
            "text": text,
            "language": language,
            "confidence": _DEFAULT_CONFIDENCE,
            "segments": [],
        }

    def transcribe(self, audio_path: str, language: Optional[str] = None) -> dict:
        if self.model is None:
            return {
                "text": "",
                "error": "SenseVoice 模型未載入",
                "language": None,
                "confidence": 0.0,
            }

        if not os.path.exists(audio_path):
            return {
                "text": "",
                "error": f"音訊文件不存在: {audio_path}",
                "language": None,
                "confidence": 0.0,
            }

        try:
            lang = language or self.language
            logger.info("[ASR] SenseVoice 開始轉錄: {}", audio_path)
            res = self.model.generate(
                input=audio_path, cache={}, language=lang, use_itn=True, batch_size_s=60
            )
            return self._parse_sensevoice_result(res, lang)
        except Exception as e:
            logger.exception("[ASR] SenseVoice 轉錄失敗")
            return {"text": "", "error": str(e), "language": None, "confidence": 0.0}

    def transcribe_bytes(self, wav_bytes: bytes, language: Optional[str] = None) -> dict:
        """WAV bytes 直接轉錄，省去 tempfile I/O"""
        if self.model is None:
            return {
                "text": "",
                "error": "SenseVoice 模型未載入",
                "language": None,
                "confidence": 0.0,
            }

        try:
            ndarray, _ = _wav_bytes_to_ndarray(wav_bytes)
            lang = language or self.language
            logger.info("[ASR] SenseVoice 開始轉錄（bytes 介面）")
            res = self.model.generate(
                input=ndarray, cache={}, language=lang, use_itn=True, batch_size_s=60
            )
            return self._parse_sensevoice_result(res, lang)
        except Exception as e:
            logger.exception("[ASR] SenseVoice 轉錄失敗（bytes 介面）")
            return {"text": "", "error": str(e), "language": None, "confidence": 0.0}


def create_asr_service(backend: str = "sensevoice", **kwargs):
    """工廠函式：依 backend 建立 ASR 服務"""
    if backend == "sensevoice":
        from src.config.models import SENSEVOICE_MODEL, SENSEVOICE_HUB

        return SenseVoiceService(model_id=SENSEVOICE_MODEL, hub=SENSEVOICE_HUB, **kwargs)
    else:
        return ASRService(**kwargs)
