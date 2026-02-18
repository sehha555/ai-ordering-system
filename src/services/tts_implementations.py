# src/services/tts_implementations.py
import asyncio
import io
from typing import AsyncIterator
import edge_tts
from loguru import logger
from src.services.tts_interface import TTSModel


class EdgeTTSModel(TTSModel):
    def __init__(self, voice: str = "zh-TW-HsiaoChenNeural"):
        self.voice = voice

    async def run_stream(self, text: str) -> AsyncIterator[bytes]:
        communicate = edge_tts.Communicate(text, self.voice)
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                yield chunk["data"]


class Qwen3TTSModel(TTSModel):
    """使用 Qwen3-TTS 1.7B 本地模型的 TTS 服務"""

    def __init__(self, model_id: str = "Qwen/Qwen3-TTS-1.7B"):
        self._model_id = model_id
        self._pipe = None
        self._load()

    def _load(self):
        try:
            import torch
            from transformers import pipeline

            device = 0 if torch.cuda.is_available() else -1
            logger.info(f"[TTS] 正在載入 Qwen3-TTS {self._model_id}...")
            self._pipe = pipeline(
                "text-to-speech",
                model=self._model_id,
                device=device,
                torch_dtype=torch.float16 if device >= 0 else torch.float32,
            )
            logger.info("[TTS] Qwen3-TTS 模型已載入")
        except ImportError:
            logger.error("[TTS] 未安裝 transformers，請執行: pip install transformers")
        except Exception as e:
            logger.error(f"[TTS] Qwen3-TTS 載入失敗: {e}")

    def _synthesize(self, text: str) -> bytes:
        """同步合成，回傳 WAV bytes"""
        import scipy.io.wavfile as wavfile
        import numpy as np

        output = self._pipe(text)
        rate = output["sampling_rate"]
        audio = output["audio"]
        if audio.ndim > 1:
            audio = audio[0]
        audio_int16 = (audio * 32767).astype(np.int16)
        buf = io.BytesIO()
        wavfile.write(buf, rate, audio_int16)
        return buf.getvalue()

    async def run_stream(self, text: str) -> AsyncIterator[bytes]:
        if self._pipe is None:
            logger.error("[TTS] Qwen3-TTS 未載入，無法合成語音")
            return

        loop = asyncio.get_event_loop()
        audio_bytes = await loop.run_in_executor(None, self._synthesize, text)
        yield audio_bytes


def create_tts_model(backend: str = "edgetts") -> TTSModel:
    """工廠函式：依 backend 建立 TTS 模型"""
    if backend == "qwen3tts":
        from src.config.models import QWEN3TTS_MODEL
        return Qwen3TTSModel(model_id=QWEN3TTS_MODEL)
    else:
        return EdgeTTSModel()
