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
    """Qwen3-TTS 本地模型，輸出 MP3 bytes（與 Edge TTS 格式一致）"""

    def __init__(
        self,
        model_id: str = "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice",
        speaker: str = "Vivian",
    ):
        self._model_id = model_id
        self._speaker = speaker
        self._model = None
        self._fallback = EdgeTTSModel()
        self._load()

    def _load(self):
        try:
            import torch
            from qwen_tts import Qwen3TTSModel as _Qwen3TTS

            dtype = torch.bfloat16 if torch.cuda.is_available() else torch.float32
            device_map = "cuda:0" if torch.cuda.is_available() else "cpu"
            logger.info("[TTS] 正在載入 Qwen3-TTS {}...", self._model_id)
            self._model = _Qwen3TTS.from_pretrained(
                self._model_id,
                device_map=device_map,
                dtype=dtype,
            )
            logger.info("[TTS] Qwen3-TTS 已載入，speaker={}", self._speaker)
        except ImportError:
            logger.error("[TTS] 未安裝 qwen-tts，將 fallback 到 Edge TTS")
        except Exception as e:
            logger.error("[TTS] Qwen3-TTS 載入失敗: {}，將 fallback 到 Edge TTS", e)

    def _synthesize_mp3(self, text: str) -> bytes:
        """同步合成，回傳 MP3 bytes"""
        import numpy as np
        from pydub import AudioSegment

        wavs, sr = self._model.generate_custom_voice(
            text=text,
            language="Chinese",
            speaker=self._speaker,
        )
        audio = wavs[0] if isinstance(wavs, list) else wavs
        if hasattr(audio, "cpu"):
            audio = audio.cpu().numpy()
        audio = np.array(audio, dtype=np.float32)
        if audio.ndim > 1:
            audio = audio[0]
        # float32 → int16 PCM
        audio_int16 = (audio * 32767).clip(-32768, 32767).astype(np.int16)

        # PCM → MP3（透過 pydub + ffmpeg）
        segment = AudioSegment(
            data=audio_int16.tobytes(),
            sample_width=2,  # 16-bit
            frame_rate=sr,
            channels=1,
        )
        buf = io.BytesIO()
        segment.export(buf, format="mp3", bitrate="128k")
        return buf.getvalue()

    async def run_stream(self, text: str) -> AsyncIterator[bytes]:
        # 模型未載入 → fallback Edge TTS
        if self._model is None:
            logger.warning("[TTS] Qwen3-TTS 未載入，fallback 到 Edge TTS")
            async for chunk in self._fallback.run_stream(text):
                yield chunk
            return

        try:
            loop = asyncio.get_event_loop()
            audio_bytes = await loop.run_in_executor(None, self._synthesize_mp3, text)
            yield audio_bytes
        except Exception as e:
            logger.error("[TTS] Qwen3-TTS 合成失敗: {}，fallback 到 Edge TTS", e)
            async for chunk in self._fallback.run_stream(text):
                yield chunk


def create_tts_model(backend: str = "edgetts") -> TTSModel:
    """工廠函式：依 backend 建立 TTS 模型"""
    if backend == "qwen3tts":
        from src.config.models import QWEN3TTS_MODEL, QWEN3TTS_SPEAKER

        return Qwen3TTSModel(model_id=QWEN3TTS_MODEL, speaker=QWEN3TTS_SPEAKER)
    else:
        return EdgeTTSModel()
