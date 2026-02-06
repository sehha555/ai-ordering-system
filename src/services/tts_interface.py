# src/services/tts_interface.py
from abc import ABC, abstractmethod
from typing import AsyncIterator


class TTSModel(ABC):
    @abstractmethod
    async def run_stream(self, text: str) -> AsyncIterator[bytes]:
        """Yields audio chunks (PCM or MP3 frames)"""
        pass
