# src/services/streaming_orchestrator.py
import json
import base64
from typing import AsyncIterator, Dict, Any


class StreamingOrchestrator:
    def __init__(self, asr_service, dialogue_manager, tts_service, session_id: str = None):
        self.asr = asr_service
        self.dm = dialogue_manager
        self.tts = tts_service
        self.session_id = session_id

    async def process_audio_stream(self, audio_bytes: bytes, session_id: str = None) -> AsyncIterator[Dict[str, Any]]:
        # 使用傳入的 session_id 或使用初始化時的 session_id
        if session_id:
            self.session_id = session_id

        # 1. Thinking
        yield {"event": "thinking", "data": {}}

        # 2. ASR
        text = await self.asr.transcribe(audio_bytes)
        yield {"event": "transcription", "data": {"text": text}}

        # 3. DM
        response_text, context_snapshot = self.dm.process_input(text)

        # 4. Cart Update
        cart = context_snapshot.get("cart", [])
        total = context_snapshot.get("order_payload", {}).get("total_price", 0)
        yield {"event": "cart_update", "data": {"items": cart, "total": total}}

        # 5. TTS Streaming
        async for chunk in self.tts.run_stream(response_text):
            b64_audio = base64.b64encode(chunk).decode('utf-8')
            yield {"event": "audio_chunk", "data": b64_audio}
