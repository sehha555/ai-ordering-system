# src/services/tts_implementations.py
import asyncio
import io
import time
from typing import AsyncIterator
import edge_tts
import httpx
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


class OmniVoiceTTSModel(TTSModel):
    """OmniVoice TTS — 透過 HTTP 呼叫獨立微服務（避免 transformers 版本衝突）

    微服務啟動：python src/services/omnivoice_server.py --port 8100
    """

    # Circuit breaker: 連線失敗後跳過 OmniVoice 一段時間，避免每句都 timeout
    _circuit_open_until: float = 0.0  # class-level，所有 instance 共享
    _CIRCUIT_COOLDOWN = 60.0  # 失敗後 60 秒內直接走 fallback

    def __init__(self, base_url: str = "http://127.0.0.1:8100"):
        self._base_url = base_url
        self._client = httpx.AsyncClient(base_url=base_url, timeout=30.0)
        self._fallback = EdgeTTSModel()
        logger.info("[TTS] OmniVoice client 初始化 ({})", base_url)

    async def run_stream(self, text: str) -> AsyncIterator[bytes]:
        now = time.monotonic()
        if now < OmniVoiceTTSModel._circuit_open_until:
            async for chunk in self._fallback.run_stream(text):
                yield chunk
            return

        try:
            r = await self._client.post("/synthesize", json={"text": text})
            if r.status_code == 200:
                yield r.content
                return
            logger.warning("[TTS] OmniVoice 合成失敗 ({}), fallback Edge TTS", r.status_code)
            if r.status_code >= 500:
                OmniVoiceTTSModel._circuit_open_until = time.monotonic() + self._CIRCUIT_COOLDOWN
        except Exception as e:
            logger.warning(
                "[TTS] OmniVoice 請求失敗: {}，circuit breaker 啟動 {}s", e, self._CIRCUIT_COOLDOWN
            )
            OmniVoiceTTSModel._circuit_open_until = time.monotonic() + self._CIRCUIT_COOLDOWN

        async for chunk in self._fallback.run_stream(text):
            yield chunk


def create_tts_model(backend: str = "edgetts") -> TTSModel:
    """工廠函式：依 backend 建立 TTS 模型"""
    if backend == "qwen3tts":
        from src.config.models import QWEN3TTS_MODEL, QWEN3TTS_SPEAKER

        return Qwen3TTSModel(model_id=QWEN3TTS_MODEL, speaker=QWEN3TTS_SPEAKER)
    elif backend == "omnivoice":
        from src.config.models import OMNIVOICE_BASE_URL

        return OmniVoiceTTSModel(base_url=OMNIVOICE_BASE_URL)
    else:
        return EdgeTTSModel()
