# src/services/streaming_orchestrator.py
import asyncio
import json
import base64
import time
from typing import AsyncIterator, Dict, Any
from loguru import logger
from src.utils.perf_collector import perf_collector


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

        request_start = time.perf_counter()
        logger.info("[SSE] 開始處理音訊串流, session_id={}", self.session_id)

        # 1. Thinking
        yield {"event": "thinking", "data": {}}

        # 2. ASR
        asr_start = time.perf_counter()
        text = await self.asr.transcribe(audio_bytes)
        asr_elapsed = time.perf_counter() - asr_start
        logger.info("[PERF] asr_transcribe 耗時 {:.3f}s", asr_elapsed)
        yield {"event": "transcription", "data": {"text": text}}

        if not text:
            logger.warning("[SSE] ASR 無法識別語音，中止處理")
            yield {"event": "error", "data": {"message": "無法識別語音內容，請再試一次"}}
            return

        # 3. DM
        dm_start = time.perf_counter()
        loop = asyncio.get_event_loop()
        response_text, context_snapshot = await loop.run_in_executor(None, self.dm.process_input, text)
        dm_elapsed = time.perf_counter() - dm_start
        logger.info("[PERF] dm_process 耗時 {:.3f}s", dm_elapsed)

        # 4. Cart Update
        cart = context_snapshot.get("cart", [])
        total = context_snapshot.get("order_payload", {}).get("total_price", 0)
        yield {"event": "cart_update", "data": {"items": cart, "total": total}}

        # 4.5 Order Complete（如果有 finalize_order 結果）
        finalize_result = context_snapshot.get("finalize_result")
        if finalize_result:
            yield {"event": "order_complete", "data": finalize_result}

        # 5. TTS Streaming
        tts_start = time.perf_counter()
        ttfa_elapsed = None
        first_chunk = True
        async for chunk in self.tts.run_stream(response_text):
            b64_audio = base64.b64encode(chunk).decode('utf-8')
            yield {"event": "audio_chunk", "data": b64_audio}
            if first_chunk:
                ttfa_elapsed = time.perf_counter() - request_start
                logger.info("[PERF] TTFA 首個音訊 {:.3f}s", ttfa_elapsed)
                first_chunk = False
        tts_elapsed = time.perf_counter() - tts_start
        logger.info("[PERF] tts_stream 耗時 {:.3f}s", tts_elapsed)

        total_elapsed = time.perf_counter() - request_start
        logger.info("[PERF] 端對端 SSE 總耗時 {:.3f}s", total_elapsed)

        # 記錄到效能收集器
        perf_collector.record(
            asr_s=asr_elapsed,
            dm_s=dm_elapsed,
            ttfa_s=ttfa_elapsed,
            tts_s=tts_elapsed,
            total_s=total_elapsed,
        )
