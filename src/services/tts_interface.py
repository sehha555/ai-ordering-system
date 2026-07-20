# src/services/tts_interface.py
from abc import ABC, abstractmethod
from typing import AsyncIterator, Optional


class TTSModel(ABC):
    # 子類在 run_stream 中記錄「實際產出音訊的聲音 key」（fallback 時為 fallback 聲音）
    _last_voice_key: Optional[str] = None

    # True = run_stream 的每個 chunk 都是獨立可播放音檔（可逐段下發前端）；
    # False = chunk 是不可獨立解碼的片段（如 Edge MP3 frame），必須收齊 join 才能播
    stream_playable_chunks: bool = False

    @abstractmethod
    async def run_stream(self, text: str) -> AsyncIterator[bytes]:
        """Yields audio chunks (PCM or MP3 frames)"""
        pass

    @property
    def cache_voice_key(self) -> str:
        """TTS cache 聲音維度 key，子類別覆寫以區分不同聲音身分"""
        return "default"

    @property
    def last_voice_key(self) -> str:
        """上次 run_stream 實際產出音訊的聲音 key。
        快取 put 一律用此 key，fallback 產物自然存到 fallback 聲音的 key 下，不污染本尊。"""
        return self._last_voice_key or self.cache_voice_key
