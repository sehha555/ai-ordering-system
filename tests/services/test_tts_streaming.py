# tests/services/test_tts_streaming.py
import pytest
import asyncio
from typing import AsyncIterator
from src.services.tts_interface import TTSModel

class MockTTS(TTSModel):
    async def run_stream(self, text: str) -> AsyncIterator[bytes]:
        yield b"chunk1"
        yield b"chunk2"

@pytest.mark.asyncio
async def test_tts_interface_contract():
    tts = MockTTS()
    chunks = []
    async for chunk in tts.run_stream("hello"):
        chunks.append(chunk)
    assert chunks == [b"chunk1", b"chunk2"]
