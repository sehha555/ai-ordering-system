# src/services/tts_interface.py
from abc import ABC, abstractmethod
from typing import AsyncIterator


class TTSModel(ABC):
    @abstractmethod
    async def run_stream(self, text: str) -> AsyncIterator[bytes]:
        """Yields audio chunks (PCM or MP3 frames)"""
        pass

    @property
    def cache_voice_key(self) -> str:
        """TTS cache 聲音維度 key，子類別覆寫以區分不同聲音身分"""
        return "default"
